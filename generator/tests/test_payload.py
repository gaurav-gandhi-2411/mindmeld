from __future__ import annotations

"""
Unit tests for payload schema, anti-cheat keying, and secret obfuscation.

Uses a tiny stub vocab (10 words) with hardcoded numpy arrays so no
sentence-transformers model is needed.

Section F: alt-map tests use a hi-en stub vocab that includes words with
doubled-vowel canonicals (baarish, chaand, gyaan) so the normalize() and
alias rules produce variant hashes to test against.
"""

import base64
import gzip
import io
import json
from datetime import date

import numpy as np
import pytest

from normalize import normalize
from payload import (
    _is_morphological_variant,
    _word_hash,
    build_payload,
    decode_secret,
    levenshtein,
    write_payload,
)

# ---------------------------------------------------------------------------
# Stub data — deterministic, no model needed
# ---------------------------------------------------------------------------

_STUB_VOCAB = [
    "ocean",
    "sea",
    "mountain",
    "rain",
    "book",
    "music",
    "friend",
    "bread",
    "fire",
    "flower",
]
_STUB_DIM = 4
_SEED = 42
_rng = np.random.default_rng(_SEED)
# Random unit-normalised float32 vectors; fixed seed guarantees reproducibility
_raw = _rng.standard_normal((len(_STUB_VOCAB), _STUB_DIM)).astype(np.float32)
_norms = np.linalg.norm(_raw, axis=1, keepdims=True)
_STUB_MATRIX = (_raw / _norms).astype(np.float32)

_PUZZLE_DATE = date(2026, 6, 12)
_LANG = "en"
_SECRET = "ocean"  # index 0 in stub vocab


@pytest.fixture()
def payload() -> dict:
    """Build a payload from stub data. ocean is the secret (rank 1 expected)."""
    return build_payload(_STUB_VOCAB, _STUB_MATRIX, _SECRET, _LANG, _PUZZLE_DATE)


class TestPayloadSchema:
    """Test that required keys exist and have correct types."""

    def test_version_key(self, payload: dict) -> None:
        assert payload["v"] == 3

    def test_lang_key(self, payload: dict) -> None:
        assert payload["lang"] == _LANG

    def test_date_key(self, payload: dict) -> None:
        assert payload["date"] == _PUZZLE_DATE.isoformat()

    def test_model_key_is_string(self, payload: dict) -> None:
        assert isinstance(payload["model"], str) and len(payload["model"]) > 0

    def test_n_equals_vocab_size(self, payload: dict) -> None:
        assert payload["n"] == len(_STUB_VOCAB)

    def test_salt_is_16_char_hex(self, payload: dict) -> None:
        salt = payload["salt"]
        assert isinstance(salt, str) and len(salt) == 16
        int(salt, 16)  # raises ValueError if not valid hex

    def test_words_key_exists(self, payload: dict) -> None:
        assert "words" in payload

    def test_words_has_correct_count(self, payload: dict) -> None:
        assert len(payload["words"]) == len(_STUB_VOCAB)

    def test_hints_key_exists(self, payload: dict) -> None:
        assert "hints" in payload

    def test_s_key_exists(self, payload: dict) -> None:
        assert "s" in payload

    def test_s_is_base64(self, payload: dict) -> None:
        base64.b64decode(payload["s"])  # should not raise

    def test_clue_key_exists(self, payload: dict) -> None:
        assert "clue" in payload
        assert isinstance(payload["clue"], str)

    def test_max_guesses_key_exists(self, payload: dict) -> None:
        assert "maxGuesses" in payload
        assert isinstance(payload["maxGuesses"], int)
        assert payload["maxGuesses"] > 0


class TestAntiCheatKeying:
    """Test that the secret word cannot be found as a plaintext JSON key."""

    def test_secret_not_a_key_in_words(self, payload: dict) -> None:
        words = payload["words"]
        assert _SECRET not in words, "Secret word must not appear as a plaintext JSON key"

    def test_secret_not_in_words_values_as_string(self, payload: dict) -> None:
        """Confirm the secret doesn't appear as a raw string in the words dict values."""
        for _key, val in payload["words"].items():
            for item in val:
                assert item != _SECRET

    def test_words_keys_are_12char_hex(self, payload: dict) -> None:
        for k in payload["words"]:
            assert len(k) == 12, f"Hash key {k!r} is not 12 chars"
            int(k, 16)  # raises if not hex

    def test_words_values_are_rank_qsim_pairs(self, payload: dict) -> None:
        for _k, v in payload["words"].items():
            assert isinstance(v, list) and len(v) == 2
            rank, qsim = v
            assert isinstance(rank, int) and rank >= 1
            assert isinstance(qsim, int) and 0 <= qsim <= 65535

    def test_secret_maps_to_rank_one(self, payload: dict) -> None:
        """Find the hash for the secret word and verify its rank is 1."""
        salt = payload["salt"]
        secret_hash = _word_hash(_SECRET, salt)
        assert secret_hash in payload["words"], "Secret hash not found in words"
        rank, _ = payload["words"][secret_hash]
        assert rank == 1, f"Secret word has rank {rank}, expected 1"

    def test_no_other_word_has_rank_one(self, payload: dict) -> None:
        """Exactly one word should have rank 1."""
        rank_one_count = sum(1 for rank, _ in payload["words"].values() if rank == 1)
        assert rank_one_count == 1

    def test_secret_plaintext_not_as_json_key(self, payload: dict) -> None:
        """
        After JSON serialisation, the secret must not appear as a top-level or
        words-dict key in plaintext — only as a hash-keyed entry or inside the
        obfuscated "s" field.
        """
        json_str = json.dumps(payload)
        # Check: the literal string '"ocean"' as a JSON key should not appear
        # (it can appear as a value in hints, but the test secret "ocean"
        # is not at rank 2 in the tiny stub so it won't be in hints either).
        as_key = f'"{_SECRET}":'
        assert as_key not in json_str, f"Secret {_SECRET!r} found as JSON key"


class TestHintsSchemaAndExclusion:
    """Test hint list schema and that rank 1 (secret) is never in hints."""

    def test_hints_are_list(self, payload: dict) -> None:
        assert isinstance(payload["hints"], list)

    def test_hints_are_rank_word_pairs(self, payload: dict) -> None:
        for hint in payload["hints"]:
            assert isinstance(hint, list) and len(hint) == 2
            rank, word = hint
            assert isinstance(rank, int) and rank >= 1
            assert isinstance(word, str)

    def test_rank_one_not_in_hints(self, payload: dict) -> None:
        """The secret (rank 1) must never appear in plaintext hints."""
        for rank, word in payload["hints"]:
            assert rank != 1, f"Rank 1 (secret) found in hints: {word!r}"
            assert word != _SECRET, f"Secret word {_SECRET!r} found in hint plaintext"


class TestDecodeSecretRoundTrip:
    """Test that decode_secret(payload) recovers the original secret."""

    def test_decode_matches_secret(self, payload: dict) -> None:
        recovered = decode_secret(payload)
        assert recovered == _SECRET

    def test_different_secrets_different_s_fields(self) -> None:
        """Two payloads with different secrets must produce different "s" fields."""
        p1 = build_payload(_STUB_VOCAB, _STUB_MATRIX, "ocean", _LANG, _PUZZLE_DATE)
        p2 = build_payload(_STUB_VOCAB, _STUB_MATRIX, "sea", _LANG, _PUZZLE_DATE)
        assert p1["s"] != p2["s"]

    def test_decode_is_deterministic(self, payload: dict) -> None:
        r1 = decode_secret(payload)
        r2 = decode_secret(payload)
        assert r1 == r2


class TestPayloadEdgeCases:
    """Edge cases and error handling."""

    def test_raises_if_secret_not_in_vocab(self) -> None:
        with pytest.raises(ValueError, match="not in vocab"):
            build_payload(_STUB_VOCAB, _STUB_MATRIX, "notinvocab", _LANG, _PUZZLE_DATE)

    def test_no_hash_collisions_in_stub(self, payload: dict) -> None:
        """All hashes in the words dict are unique (assert in build_payload already)."""
        hashes = list(payload["words"].keys())
        assert len(hashes) == len(set(hashes))


# ---------------------------------------------------------------------------
# Finding 2: Levenshtein helper and morphological variant filter
# ---------------------------------------------------------------------------


class TestLevenshtein:
    """Unit tests for the levenshtein() helper."""

    def test_identical_strings(self) -> None:
        assert levenshtein("ocean", "ocean") == 0

    def test_single_insertion(self) -> None:
        assert levenshtein("ocean", "oceans") == 1

    def test_single_deletion(self) -> None:
        assert levenshtein("oceans", "ocean") == 1

    def test_single_substitution(self) -> None:
        assert levenshtein("cat", "bat") == 1

    def test_completely_different(self) -> None:
        # "abc" → "xyz": 3 substitutions
        assert levenshtein("abc", "xyz") == 3

    def test_empty_strings(self) -> None:
        assert levenshtein("", "") == 0
        assert levenshtein("abc", "") == 3
        assert levenshtein("", "abc") == 3

    def test_plural_is_distance_one(self) -> None:
        assert levenshtein("mountain", "mountains") == 1


class TestMorphologicalVariantFilter:
    """Unit tests for _is_morphological_variant()."""

    def test_plural_is_variant(self) -> None:
        assert _is_morphological_variant("oceans", "ocean") is True

    def test_prefix_match_is_variant(self) -> None:
        # "oceanic" starts with "ocean"
        assert _is_morphological_variant("oceanic", "ocean") is True

    def test_secret_is_prefix_of_candidate(self) -> None:
        assert _is_morphological_variant("ocean", "oceans") is True

    def test_edit_distance_two_is_variant(self) -> None:
        # "oceane" — edit distance 2 from "ocean"
        assert _is_morphological_variant("oceane", "ocean") is True

    def test_clearly_different_word_not_variant(self) -> None:
        assert _is_morphological_variant("mountain", "ocean") is False

    def test_similar_but_beyond_threshold(self) -> None:
        # "river" vs "ocean" — edit distance > 2, no prefix relationship
        assert _is_morphological_variant("river", "ocean") is False

    def test_compound_containing_secret_is_variant(self) -> None:
        # "gunfire" contains "fire" — would leak the secret as a substring in JSON
        assert _is_morphological_variant("gunfire", "fire") is True

    def test_secret_contained_in_candidate_is_variant(self) -> None:
        # "campfire" contains "fire"
        assert _is_morphological_variant("campfire", "fire") is True

    # -----------------------------------------------------------------------
    # Length-scaled threshold — a flat distance-2 (or unconditional substring)
    # check over-fires on short secrets. See the module-level regression tests
    # below (test_short_secret_...) for the exact previously-reported false
    # positives this fixes: 3-letter "bat" flagging ball/wait/both, 5-letter
    # "money" flagging "more", and 6-letter "mandir" flagging "and" (the last
    # via the plain-substring check, not Levenshtein — "and" is a coincidental
    # substring of "mandir", not a morphological relative of it).
    # -----------------------------------------------------------------------

    def test_short_secret_no_longer_flags_unrelated_distance_two_words(self) -> None:
        # "bat" (3 letters): distance 2 from all three, previously flagged.
        assert _is_morphological_variant("ball", "bat") is False
        assert _is_morphological_variant("wait", "bat") is False
        assert _is_morphological_variant("both", "bat") is False

    def test_medium_short_secret_no_longer_flags_unrelated_distance_two_word(self) -> None:
        # "money" (5 letters) vs "more": distance 2, shorter string ("more") is
        # only 4 characters, so the length-scaled threshold is 1, not 2.
        assert _is_morphological_variant("more", "money") is False

    def test_short_candidate_substring_of_secret_not_flagged(self) -> None:
        # "and" (3 letters) is a coincidental substring of "mandir" — not a
        # real spoiler risk, and not caught by Levenshtein either (distance 3).
        assert _is_morphological_variant("and", "mandir") is False

    def test_short_distance_one_variant_still_flagged(self) -> None:
        # Distance 1 remains a real risk even for very short secrets: "fix"
        # and "mix" are genuine near-typo lookalikes of "six".
        assert _is_morphological_variant("fix", "six") is True
        assert _is_morphological_variant("mix", "six") is True

    def test_four_letter_compound_boundary_still_flagged(self) -> None:
        # Boundary check: the substring rule's >=4 minimum-length guard must
        # not regress the existing "fire"/"gunfire" case above (secret "fire"
        # is exactly 4 characters, the guard's own threshold).
        assert _is_morphological_variant("bonfire", "fire") is True


class TestHintMorphologicalExclusion:
    """
    Verify that hint selection skips morphological variants of the secret.

    We construct a vocab + embedding matrix where we can predict the similarity
    ranking, ensuring the secret's plural appears at rank 2 and confirm it is
    NOT chosen as a hint.
    """

    def test_plural_not_chosen_as_hint(self) -> None:
        """
        Secret is "cloud". Vocab includes "clouds" (its plural) placed at rank 2
        via embeddings. The hint for target rank 2 must NOT be "clouds".
        """
        # Build a vocab where "cloud" is the secret and we can control similarity.
        # We make "clouds" the closest non-secret neighbour by giving it a vector
        # nearly identical to "cloud".
        secret = "cloud"
        vocab = [secret, "clouds", "rain", "mountain", "river", "sunny"]
        dim = 8
        rng = np.random.default_rng(99)
        raw = rng.standard_normal((len(vocab), dim)).astype(np.float32)
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        matrix = (raw / norms).astype(np.float32)

        # Force "clouds" to be nearly identical to "cloud" (rank 2 slot)
        matrix[1] = matrix[0] + 0.001 * rng.standard_normal(dim).astype(np.float32)
        matrix[1] = (matrix[1] / np.linalg.norm(matrix[1])).astype(np.float32)

        payload = build_payload(vocab, matrix, secret, "en", date(2026, 6, 12))

        # Collect all hint words
        hint_words = [word for _rank, word in payload["hints"]]
        assert "clouds" not in hint_words, (
            f"Morphological variant 'clouds' must not appear in hints; got hints={payload['hints']}"
        )

    def test_secret_not_substring_in_json(self, payload: dict) -> None:
        """
        The plaintext secret must not appear as a substring anywhere in the emitted JSON.
        (The obfuscated 's' field renders it safe; hints are filtered.)
        """
        json_str = json.dumps(payload)
        assert _SECRET not in json_str, (
            f"Secret {_SECRET!r} found as a substring in the emitted JSON"
        )


# ---------------------------------------------------------------------------
# Finding 3: gzip reproducibility (mtime=0)
# ---------------------------------------------------------------------------


class TestGzipReproducibility:
    """Verify that write_payload produces identical bytes across runs."""

    def test_compress_same_dict_twice_identical_bytes(self, tmp_path: object) -> None:
        """
        Compressing the same payload dict twice must yield byte-for-byte identical .json.gz.
        This fails if gzip embeds a wall-clock timestamp (mtime != 0).
        """
        assert isinstance(tmp_path, type(tmp_path))  # tmp_path is pytest's Path fixture
        from pathlib import Path

        out = Path(str(tmp_path))
        p = build_payload(_STUB_VOCAB, _STUB_MATRIX, _SECRET, _LANG, _PUZZLE_DATE)

        path1 = write_payload(p, out / "run1", _LANG, _PUZZLE_DATE)
        path2 = write_payload(p, out / "run2", _LANG, _PUZZLE_DATE)

        assert path1.read_bytes() == path2.read_bytes(), (
            "gzip output differs between runs — mtime=0 not set correctly"
        )

    def test_gzip_with_mtime0_is_deterministic(self) -> None:
        """
        Low-level confirmation: two GzipFile(mtime=0) compressions of the same
        bytes produce identical output regardless of when they run.
        """
        data = b'{"test": "payload", "n": 42}'

        def compress_with_mtime0(payload_bytes: bytes) -> bytes:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
                gz.write(payload_bytes)
            return buf.getvalue()

        first = compress_with_mtime0(data)
        second = compress_with_mtime0(data)
        assert first == second, "mtime=0 gzip compression must be deterministic"

    def test_payload_bytes_stable_across_hash_seeds(self) -> None:
        """
        Regression: payload bytes must not depend on the per-process string-hash
        seed. The alt-map builder once collected variants in a set and serialized
        them in set-iteration order, so hi-en payloads differed byte-for-byte
        between processes (PYTHONHASHSEED). Runs the build in subprocesses with
        different seeds and asserts identical output bytes.
        """
        import os
        import subprocess
        import sys
        from pathlib import Path

        generator_dir = Path(__file__).resolve().parent.parent
        script = """
import hashlib, io, json, sys
from datetime import date
import numpy as np
import payload as payload_mod

# Synthetic alias map with multiple aliases per canonical so each word's
# candidate set has >1 element — the order-sensitive path.
payload_mod.load_alias_map = lambda: {
    "barrish": "baarish", "baarysh": "baarish", "bariish": "baarish",
    "chandd": "chaand", "chaind": "chaand",
    "gyann": "gyaan",
}

vocab = ["baarish", "chaand", "gyaan", "rain", "friend", "cloud"]
rng = np.random.default_rng(7)
raw = rng.standard_normal((len(vocab), 4)).astype(np.float32)
matrix = (raw / np.linalg.norm(raw, axis=1, keepdims=True)).astype(np.float32)

p = payload_mod.build_payload(vocab, matrix, "baarish", "hi-en", date(2026, 6, 13))
blob = json.dumps(p, separators=(",", ":"), ensure_ascii=False).encode()
print(hashlib.sha256(blob).hexdigest())
"""
        digests = []
        for seed in ("1", "2", "3"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run(  # noqa: S603
                [sys.executable, "-c", script],
                cwd=str(generator_dir),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            digests.append(result.stdout.strip())

        assert len(set(digests)) == 1, f"payload bytes vary with PYTHONHASHSEED: {digests}"


# ---------------------------------------------------------------------------
# Alt-map tests (hi-en only)
# ---------------------------------------------------------------------------

# Hi-en stub vocab with words that have normalization variants and aliases.
# "baarish" normalizes to "barish" (aa→a) — variant hash goes into alt.
# "chaand" normalizes to "chand" (aa→a) — variant hash goes into alt.
# "gyaan" normalizes to "gyan" (aa→a) — variant hash goes into alt.
# The English words (rain, friend, cloud) have no normalization variants.
_HIEN_STUB_VOCAB = [
    "baarish",  # secret — index 0, rank 1; normalizes to "barish"
    "chaand",  # rank 2+; normalizes to "chand"
    "gyaan",  # rank 3+; normalizes to "gyan"
    "rain",  # plain English — no variants
    "friend",  # plain English — no variants
    "cloud",  # plain English — no variants
]
_HIEN_DIM = 4
_hien_rng = np.random.default_rng(7)
_hien_raw = _hien_rng.standard_normal((len(_HIEN_STUB_VOCAB), _HIEN_DIM)).astype(np.float32)
_hien_norms = np.linalg.norm(_hien_raw, axis=1, keepdims=True)
_HIEN_STUB_MATRIX = (_hien_raw / _hien_norms).astype(np.float32)

_HIEN_DATE = date(2026, 6, 13)
_HIEN_LANG = "hi-en"
_HIEN_SECRET = "baarish"


@pytest.fixture()
def hien_payload() -> dict:
    """Build a hi-en payload from stub hi-en data. baarish is the secret."""
    return build_payload(_HIEN_STUB_VOCAB, _HIEN_STUB_MATRIX, _HIEN_SECRET, _HIEN_LANG, _HIEN_DATE)


class TestAltMap:
    """Tests for the hi-en alt map (variant spelling → canonical rank/qsim)."""

    def test_en_payload_has_no_alt_key(self, payload: dict) -> None:
        """English payloads must NOT have an 'alt' key."""
        assert "alt" not in payload, "en payload must not have an 'alt' map"

    def test_hien_payload_has_alt_key(self, hien_payload: dict) -> None:
        """hi-en payloads with normalization variants must have an 'alt' key."""
        assert "alt" in hien_payload, "hi-en payload must have an 'alt' map"

    def test_alt_keys_are_12char_hex(self, hien_payload: dict) -> None:
        """Every key in the alt map must be a 12-char hex string."""
        for k in hien_payload.get("alt", {}):
            assert len(k) == 12, f"alt key {k!r} is not 12 chars"
            int(k, 16)  # raises if not valid hex

    def test_alt_values_are_rank_qsim_pairs(self, hien_payload: dict) -> None:
        """Every value in the alt map must be [rank, qsim] with valid ranges."""
        for _k, v in hien_payload.get("alt", {}).items():
            assert isinstance(v, list) and len(v) == 2
            rank, qsim = v
            assert isinstance(rank, int) and rank >= 1
            assert isinstance(qsim, int) and 0 <= qsim <= 65535

    def test_alt_has_no_overlap_with_words(self, hien_payload: dict) -> None:
        """No hash in alt must also appear in words — canonical entries always win."""
        words_keys = set(hien_payload["words"].keys())
        for alt_hash in hien_payload.get("alt", {}):
            assert alt_hash not in words_keys, (
                f"alt hash {alt_hash!r} also present in words — canonical should win"
            )

    def test_secret_variant_maps_to_rank_one(self, hien_payload: dict) -> None:
        """
        The normalized variant of the secret must map to rank 1 in the alt map.

        baarish normalizes to barish (aa→a); hash12("barish"+salt) → [1, qsim_of_baarish].
        """
        salt = hien_payload["salt"]
        norm_secret = normalize(_HIEN_SECRET)
        assert norm_secret != _HIEN_SECRET, (
            "Test precondition: secret must have a normalize variant"
        )

        variant_hash = _word_hash(norm_secret, salt)
        alt = hien_payload.get("alt", {})
        assert variant_hash in alt, f"Normalized variant {norm_secret!r} hash not found in alt map"
        rank, _ = alt[variant_hash]
        assert rank == 1, f"Secret variant {norm_secret!r} has rank {rank}, expected 1"

    def test_non_secret_variant_maps_to_correct_rank(self, hien_payload: dict) -> None:
        """
        A non-secret word's variant must map to that word's rank (not 1).

        chaand normalizes to chand; its alt entry rank must match its words entry rank.
        """
        salt = hien_payload["salt"]
        # Find rank of "chaand" in words
        chaand_hash = _word_hash("chaand", salt)
        chaand_rv = hien_payload["words"].get(chaand_hash)
        assert chaand_rv is not None, "'chaand' not found in words"
        expected_rank = chaand_rv[0]
        assert expected_rank != 1  # it's not the secret

        # Find variant hash for "chand" (normalize("chaand") == "chand")
        variant_hash = _word_hash("chand", salt)
        alt = hien_payload.get("alt", {})
        assert variant_hash in alt, "Variant 'chand' hash not in alt"
        actual_rank, _ = alt[variant_hash]
        assert actual_rank == expected_rank, (
            f"'chand' variant rank {actual_rank} != chaand rank {expected_rank}"
        )

    def test_n_unchanged_by_alt(self, hien_payload: dict) -> None:
        """n must equal len(words), not len(words)+len(alt)."""
        assert hien_payload["n"] == len(hien_payload["words"])
