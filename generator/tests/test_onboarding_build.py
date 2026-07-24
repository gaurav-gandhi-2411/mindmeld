from __future__ import annotations

"""
Unit tests for generator/build_onboarding.py (first-session hook onboarding puzzle).

Covers:
  - onboarding content loading (secrets_{lang}.txt / clues_{lang}.txt: exactly
    one entry each, comments/blanks skipped)
  - content validation (secret in vocab, not profane, clue doesn't leak secret)
  - build_onboarding_payload: schema, pack/idx namespacing, maxGuesses override,
    decode round-trip, reproducibility (byte-identical rebuild)
  - spoiler gate over the real onboarding content (mirrors test_clue_spoiler_gate.py)
  - band-quality gate: the REAL production vocab + cached embeddings place the
    approved example guesses in their intended teaching bands (skipped cleanly
    when the local .model-cache isn't warm for the current vocab — CI never has
    it, since .model-cache is gitignored and CI makes no network calls)
"""

import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from build_onboarding import (
    build_and_write_onboarding,
    build_onboarding_payload,
    load_onboarding_content,
    validate_onboarding_content,
    write_onboarding_payload,
)
from build_packs import aliases_for_secret, clue_leak_reason
from config import CACHE_DIR, MODELS, ONBOARDING_MAX_GUESSES
from embeddings import _cache_key, cosine_similarities, embed_vocab
from payload import decode_secret
from rival import band_for_rank
from vocab import load_en_vocab, load_hien_vocab

# ---------------------------------------------------------------------------
# Stub vocab — deterministic, no model needed (mirrors test_packs.py's stub).
# Includes "dog" and "paani" so build_onboarding_payload's real content (the
# actual production secrets) validates against this stub without a real model.
# ---------------------------------------------------------------------------

_STUB_VOCAB = [
    "dog",
    "paani",
    "bone",
    "ocean",
    "tiger",
    "lion",
    "river",
    "mountain",
    "rain",
    "book",
]
_STUB_DIM = 4
_SEED = 42
_rng = np.random.default_rng(_SEED)
_raw = _rng.standard_normal((len(_STUB_VOCAB), _STUB_DIM)).astype(np.float32)
_norms = np.linalg.norm(_raw, axis=1, keepdims=True)
_STUB_MATRIX = (_raw / _norms).astype(np.float32)


def _write_onboarding_content(content_dir: Path, lang: str, secret: str, clue: str) -> None:
    """Write a single-entry secrets_{lang}.txt / clues_{lang}.txt under content_dir."""
    content_dir.mkdir(parents=True, exist_ok=True)
    (content_dir / f"secrets_{lang}.txt").write_text(f"# test\n{secret}\n", encoding="utf-8")
    (content_dir / f"clues_{lang}.txt").write_text(f"# test\n{clue}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Content loading
# ---------------------------------------------------------------------------


class TestLoadOnboardingContent:
    """Tests for build_onboarding.load_onboarding_content()."""

    def test_loads_single_secret_clue_pair(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "ocean", "The biggest blue thing on any map")
        secret, clue = load_onboarding_content("en", content_dir=tmp_path)
        assert secret == "ocean"
        assert clue == "The biggest blue thing on any map"

    def test_lowercases_secret(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "OCEAN", "A clue")
        secret, _clue = load_onboarding_content("en", content_dir=tmp_path)
        assert secret == "ocean"

    def test_comments_and_blanks_skipped(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "secrets_en.txt").write_text(
            "# a comment\n\nocean\n\n# trailing comment\n", encoding="utf-8"
        )
        (tmp_path / "clues_en.txt").write_text("# a comment\n\nA clue\n", encoding="utf-8")
        secret, clue = load_onboarding_content("en", content_dir=tmp_path)
        assert secret == "ocean"
        assert clue == "A clue"

    def test_multiple_secrets_raises(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "secrets_en.txt").write_text("ocean\ntiger\n", encoding="utf-8")
        (tmp_path / "clues_en.txt").write_text("A clue\n", encoding="utf-8")
        with pytest.raises(ValueError, match="expected exactly 1 secret"):
            load_onboarding_content("en", content_dir=tmp_path)

    def test_multiple_clues_raises(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "secrets_en.txt").write_text("ocean\n", encoding="utf-8")
        (tmp_path / "clues_en.txt").write_text("Clue one\nClue two\n", encoding="utf-8")
        with pytest.raises(ValueError, match="expected exactly 1 clue"):
            load_onboarding_content("en", content_dir=tmp_path)


# ---------------------------------------------------------------------------
# Content validation
# ---------------------------------------------------------------------------


class TestValidateOnboardingContent:
    """Tests for build_onboarding.validate_onboarding_content()."""

    def test_valid_content_passes(self) -> None:
        validate_onboarding_content("en", _STUB_VOCAB, "ocean", "The biggest blue thing")

    def test_secret_not_in_vocab_raises(self) -> None:
        with pytest.raises(ValueError, match="not in vocab"):
            validate_onboarding_content("en", _STUB_VOCAB, "notinvocab", "A clue")

    def test_profane_secret_raises(self) -> None:
        # "ass" is in vocab/profanity_en.txt per the real blocklist.
        with pytest.raises(ValueError, match="profanity blocklist"):
            validate_onboarding_content("en", [*_STUB_VOCAB, "ass"], "ass", "A clue")

    def test_leaking_clue_raises(self) -> None:
        with pytest.raises(ValueError, match="leaks secret"):
            validate_onboarding_content("en", _STUB_VOCAB, "ocean", "The great blue ocean")


# ---------------------------------------------------------------------------
# build_onboarding_payload — schema, namespacing, reproducibility
# ---------------------------------------------------------------------------


class TestBuildOnboardingPayload:
    """Tests for build_onboarding.build_onboarding_payload() (stub vocab, no model needed)."""

    def test_pack_and_idx_fields(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "ocean", "The biggest blue thing")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=tmp_path)
        assert payload["pack"] == "onboarding"
        assert payload["idx"] == 1

    def test_max_guesses_overridden_to_fixed_budget(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "ocean", "The biggest blue thing")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=tmp_path)
        assert payload["maxGuesses"] == ONBOARDING_MAX_GUESSES
        assert payload["maxGuesses"] == 20

    def test_clue_field_matches_content(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "ocean", "The biggest blue thing on any map")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=tmp_path)
        assert payload["clue"] == "The biggest blue thing on any map"

    def test_decode_secret_round_trips(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "ocean", "The biggest blue thing")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=tmp_path)
        assert decode_secret(payload) == "ocean"

    def test_schema_has_v3_daily_fields(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "ocean", "The biggest blue thing")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=tmp_path)
        for field in ("v", "lang", "n", "salt", "words", "hints"):
            assert field in payload

    def test_key_carries_onboarding_namespace(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "ocean", "The biggest blue thing")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=tmp_path)
        assert payload["date"] == "onboarding-001"

    def test_raises_on_leaking_clue(self, tmp_path: Path) -> None:
        _write_onboarding_content(tmp_path, "en", "ocean", "The great blue ocean")
        with pytest.raises(ValueError, match="leaks secret"):
            build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=tmp_path)


class TestWriteOnboardingPayload:
    """Tests for build_onboarding.write_onboarding_payload()."""

    def test_writes_flat_lang_file(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        _write_onboarding_content(content_dir, "en", "ocean", "The biggest blue thing")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=content_dir)
        out_dir = tmp_path / "out"
        out_path = write_onboarding_payload(payload, out_dir, "en")
        assert out_path == out_dir / "onboarding" / "en.json.gz"
        assert out_path.exists()

    def test_written_bytes_decode_correctly(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        _write_onboarding_content(content_dir, "en", "ocean", "The biggest blue thing")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=content_dir)
        out_dir = tmp_path / "out"
        out_path = write_onboarding_payload(payload, out_dir, "en")
        decoded = json.loads(gzip.decompress(out_path.read_bytes()))
        assert decode_secret(decoded) == "ocean"
        assert decoded["maxGuesses"] == 20

    def test_rebuild_is_byte_identical(self, tmp_path: Path) -> None:
        content_dir = tmp_path / "content"
        _write_onboarding_content(content_dir, "en", "ocean", "The biggest blue thing")
        payload = build_onboarding_payload("en", _STUB_VOCAB, _STUB_MATRIX, content_dir=content_dir)

        out1 = write_onboarding_payload(payload, tmp_path / "out1", "en")
        out2 = write_onboarding_payload(payload, tmp_path / "out2", "en")
        assert out1.read_bytes() == out2.read_bytes()

    def test_rebuild_from_scratch_is_byte_identical(self, tmp_path: Path) -> None:
        """Rebuilding the payload dict twice from the same inputs must be byte-identical."""
        content_dir = tmp_path / "content"
        _write_onboarding_content(content_dir, "en", "ocean", "The biggest blue thing")

        payload1 = build_onboarding_payload(
            "en", _STUB_VOCAB, _STUB_MATRIX, content_dir=content_dir
        )
        payload2 = build_onboarding_payload(
            "en", _STUB_VOCAB, _STUB_MATRIX, content_dir=content_dir
        )

        out1 = write_onboarding_payload(payload1, tmp_path / "out1", "en")
        out2 = write_onboarding_payload(payload2, tmp_path / "out2", "en")
        assert out1.read_bytes() == out2.read_bytes()


class TestBuildAndWriteOnboarding:
    """
    Integration test for build_and_write_onboarding() against the REAL onboarding
    content files (generator/onboarding/*.txt) with a stub vocab/matrix — proves
    the actual production content ("dog" / "paani") round-trips end to end
    without requiring a real embedding model.
    """

    def test_en_real_content_round_trips(self, tmp_path: Path) -> None:
        out_path = build_and_write_onboarding("en", _STUB_VOCAB, _STUB_MATRIX, tmp_path)
        decoded = json.loads(gzip.decompress(out_path.read_bytes()))
        assert decode_secret(decoded) == "dog"
        assert decoded["maxGuesses"] == 20
        assert decoded["pack"] == "onboarding"
        assert decoded["idx"] == 1
        assert "Man's best friend" in decoded["clue"]

    def test_hien_real_content_round_trips(self, tmp_path: Path) -> None:
        out_path = build_and_write_onboarding("hi-en", _STUB_VOCAB, _STUB_MATRIX, tmp_path)
        decoded = json.loads(gzip.decompress(out_path.read_bytes()))
        assert decode_secret(decoded) == "paani"
        assert decoded["maxGuesses"] == 20
        assert decoded["pack"] == "onboarding"
        assert decoded["idx"] == 1


# ---------------------------------------------------------------------------
# Spoiler gate over the real onboarding content
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "hi-en"])
def test_onboarding_spoiler_gate(lang: str) -> None:
    """No onboarding clue leaks its own secret, alias, or morphological variant."""
    secret, clue = load_onboarding_content(lang)
    aliases = aliases_for_secret(secret, lang)
    leak = clue_leak_reason(clue, secret, aliases)
    assert leak is None, f"[onboarding/{lang}] secret={secret!r} — {leak}\nClue: {clue!r}"


# ---------------------------------------------------------------------------
# Band-quality gate — REAL vocab + cached embeddings
# ---------------------------------------------------------------------------


def _cache_available(vocab: list[str], lang: str) -> bool:
    """
    Return True iff the local embedding cache already has this exact vocab embedded.

    Used to skip the band-quality gate cleanly when the cache isn't warm (CI
    never has .model-cache — it's gitignored and CI makes no network calls to
    download models) instead of triggering an unwanted model download.
    """
    key = _cache_key(vocab, MODELS[lang])
    return (CACHE_DIR / f"{lang}-{key}.npy").exists()


_EN_VOCAB = load_en_vocab()
_HIEN_VOCAB = load_hien_vocab()
_EN_CACHE_AVAILABLE = _cache_available(_EN_VOCAB, "en")
_HIEN_CACHE_AVAILABLE = _cache_available(_HIEN_VOCAB, "hi-en")


def _ranks_for_secret(vocab: list[str], matrix: np.ndarray, secret: str) -> np.ndarray:
    """Return a rank array (1-based, rank 1 = secret) for `secret` against `vocab`/`matrix`."""
    secret_idx = vocab.index(secret)
    sims = cosine_similarities(matrix, matrix[secret_idx])
    order = np.argsort(-sims)
    ranks = np.empty(len(vocab), dtype=np.int32)
    for rank_minus1, idx in enumerate(order):
        ranks[idx] = rank_minus1 + 1
    return ranks


class TestOnboardingBandQuality:
    """
    Band-quality gate: the approved example guesses must land in their intended
    teaching bands against the REAL production vocab + embeddings — this is
    what makes the onboarding puzzle actually teach the hot/cold mechanic.

    Skipped cleanly (not a failure) when the local .model-cache doesn't already
    have this exact vocab embedded.
    """

    @pytest.mark.skipif(not _EN_CACHE_AVAILABLE, reason="EN embedding cache not warm locally")
    def test_en_teaching_ladder(self) -> None:
        vocab = _EN_VOCAB
        matrix = embed_vocab(vocab, "en", show_progress=False)
        n = len(vocab)
        ranks = _ranks_for_secret(vocab, matrix, "dog")

        scorching_max = max(50, int(n * 0.001))
        warm_lo = max(500, int(n * 0.01))
        # 900-rank floor, mirroring rival.band_for_rank's warm_max -- doesn't
        # bind for EN (n*0.05=2750 >> 900) but kept in sync for correctness.
        warm_hi = max(900, int(n * 0.05))

        bone_rank = int(ranks[vocab.index("bone")])
        assert warm_lo < bone_rank <= warm_hi, (
            f"'bone' rank {bone_rank} not in Warm band ({warm_lo}, {warm_hi}] for n={n}"
        )
        assert band_for_rank(bone_rank, n) == 3  # Warm

        for word in ("puppy", "pet", "animal", "cat"):
            rank = int(ranks[vocab.index(word)])
            assert rank <= scorching_max, (
                f"{word!r} rank {rank} not Scorching (<= {scorching_max}) for n={n}"
            )
            assert band_for_rank(rank, n) == 1  # Scorching

    @pytest.mark.skipif(not _HIEN_CACHE_AVAILABLE, reason="hi-en embedding cache not warm locally")
    def test_hien_teaching_ladder(self) -> None:
        vocab = _HIEN_VOCAB
        matrix = embed_vocab(vocab, "hi-en", show_progress=False)
        n = len(vocab)
        ranks = _ranks_for_secret(vocab, matrix, "paani")

        scorching_max = max(50, int(n * 0.001))
        hot_max = max(500, int(n * 0.01))

        nadi_rank = int(ranks[vocab.index("nadi")])
        assert scorching_max < nadi_rank <= hot_max, (
            f"'nadi' rank {nadi_rank} not in Hot band ({scorching_max}, {hot_max}] for n={n}"
        )
        assert band_for_rank(nadi_rank, n) == 2  # Hot

        water_rank = int(ranks[vocab.index("water")])
        assert water_rank <= scorching_max, (
            f"'water' rank {water_rank} not Scorching (<= {scorching_max}) for n={n}"
        )
        assert band_for_rank(water_rank, n) == 1  # Scorching
