from __future__ import annotations

"""
Unit tests for generator/packs.py and generator/build_packs.py (Phase 6c themed packs).

Covers:
  - packs.json loading + validation (real manifest + synthetic bad manifests)
  - pack content loading/validation against a stub vocab
  - build_pack_payload / write_pack_payload: schema, namespacing, decode round-trip
  - reproducibility (byte-identical rebuild)
  - inline spoiler gate rejects a clue leaking its secret
  - size gate enforcement under --strict-sizes
  - empty-content pack builds to count 0 gracefully
  - the daily build path is unaffected by the payload.py refactor that added
    build_pack_payload (golden hash + untouched derive_salt recipe)
"""

import gzip
import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from build_packs import build_one_pack, clue_leak_reason
from config import SALT_SUFFIX, derive_salt, derive_salt_for_key
from packs import PackMeta, load_packs_meta, validate_pack_content
from payload import build_pack_payload, build_payload, decode_secret, write_payload

# ---------------------------------------------------------------------------
# Stub vocab — deterministic, no model needed (mirrors test_payload.py's stub)
# ---------------------------------------------------------------------------

_STUB_VOCAB = ["ocean", "tiger", "lion", "river", "mountain", "rain", "book", "music"]
_STUB_DIM = 4
_SEED = 42
_rng = np.random.default_rng(_SEED)
_raw = _rng.standard_normal((len(_STUB_VOCAB), _STUB_DIM)).astype(np.float32)
_norms = np.linalg.norm(_raw, axis=1, keepdims=True)
_STUB_MATRIX = (_raw / _norms).astype(np.float32)


def _make_stub_pack(tmp_path: Path, pack_id: str = "testpack") -> PackMeta:
    """Return a live PackMeta with base_dir=tmp_path (content not yet written)."""
    return PackMeta(
        id=pack_id,
        title={"en": "Test Pack", "hi-en": "Test Pack"},
        tagline={"en": "A test pack", "hi-en": "A test pack"},
        free=True,
        status="live",
        accent="#111111",
        accent_dark="#222222",
        icon="film",
        langs=["en", "hi-en"],
        base_dir=tmp_path,
    )


def _write_pack_content(
    pack: PackMeta,
    secrets_by_lang: dict[str, list[str]],
    clues_by_lang: dict[str, list[str]],
) -> None:
    """Write secrets_{lang}.txt / clues_{lang}.txt under pack.dir for each lang given."""
    pack.dir.mkdir(parents=True, exist_ok=True)
    for lang, secrets in secrets_by_lang.items():
        (pack.dir / f"secrets_{lang}.txt").write_text(
            "# test pack secrets\n" + "\n".join(secrets) + "\n", encoding="utf-8"
        )
    for lang, clues in clues_by_lang.items():
        (pack.dir / f"clues_{lang}.txt").write_text(
            "# test pack clues\n" + "\n".join(clues) + "\n", encoding="utf-8"
        )


_SAFE_SECRETS = ["ocean", "tiger", "lion"]
_SAFE_CLUES = [
    "The biggest blue thing on any map",
    "Stripes stalk the jungle undergrowth",
    "Roars atop the savanna food chain",
]


# ---------------------------------------------------------------------------
# packs.json loading + validation
# ---------------------------------------------------------------------------


class TestLoadPacksMeta:
    """Tests for load_packs_meta() against the real packs.json and synthetic manifests."""

    def test_real_manifest_loads_three_packs(self) -> None:
        packs = load_packs_meta()
        ids = [p.id for p in packs]
        assert ids == ["bollywood", "cricket", "indian-food"]

    def test_bollywood_is_live_and_free(self) -> None:
        packs = {p.id: p for p in load_packs_meta()}
        assert packs["bollywood"].status == "live"
        assert packs["bollywood"].free is True

    def test_cricket_is_live_and_paid(self) -> None:
        packs = {p.id: p for p in load_packs_meta()}
        assert packs["cricket"].status == "live"
        assert packs["cricket"].free is False

    def test_indian_food_is_live_and_paid(self) -> None:
        packs = {p.id: p for p in load_packs_meta()}
        assert packs["indian-food"].status == "live"
        assert packs["indian-food"].free is False

    def test_all_packs_have_both_langs(self) -> None:
        for pack in load_packs_meta():
            assert pack.langs == ["en", "hi-en"]

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        manifest = tmp_path / "packs.json"
        manifest.write_text(json.dumps([{"id": "broken"}]), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required field"):
            load_packs_meta(path=manifest)

    def test_invalid_status_raises(self, tmp_path: Path) -> None:
        entry = {
            "id": "broken",
            "title": {"en": "x", "hi-en": "x"},
            "tagline": {"en": "x", "hi-en": "x"},
            "free": True,
            "status": "not_a_real_status",
            "accent": "#000000",
            "accentDark": "#000000",
            "icon": "film",
            "langs": ["en", "hi-en"],
        }
        manifest = tmp_path / "packs.json"
        manifest.write_text(json.dumps([entry]), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid status"):
            load_packs_meta(path=manifest)

    def test_title_missing_lang_key_raises(self, tmp_path: Path) -> None:
        entry = {
            "id": "broken",
            "title": {"en": "x"},  # missing hi-en
            "tagline": {"en": "x", "hi-en": "x"},
            "free": True,
            "status": "live",
            "accent": "#000000",
            "accentDark": "#000000",
            "icon": "film",
            "langs": ["en", "hi-en"],
        }
        manifest = tmp_path / "packs.json"
        manifest.write_text(json.dumps([entry]), encoding="utf-8")
        with pytest.raises(ValueError, match="missing lang key"):
            load_packs_meta(path=manifest)

    def test_non_bool_free_raises(self, tmp_path: Path) -> None:
        entry = {
            "id": "broken",
            "title": {"en": "x", "hi-en": "x"},
            "tagline": {"en": "x", "hi-en": "x"},
            "free": "yes",
            "status": "live",
            "accent": "#000000",
            "accentDark": "#000000",
            "icon": "film",
            "langs": ["en", "hi-en"],
        }
        manifest = tmp_path / "packs.json"
        manifest.write_text(json.dumps([entry]), encoding="utf-8")
        with pytest.raises(ValueError, match="'free' must be a boolean"):
            load_packs_meta(path=manifest)

    def test_top_level_not_a_list_raises(self, tmp_path: Path) -> None:
        manifest = tmp_path / "packs.json"
        manifest.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with pytest.raises(ValueError, match="must be a list"):
            load_packs_meta(path=manifest)

    def test_pack_dir_resolves_next_to_synthetic_manifest(self, tmp_path: Path) -> None:
        """PackMeta.dir must resolve under the tmp manifest's own directory."""
        entry = {
            "id": "mypack",
            "title": {"en": "x", "hi-en": "x"},
            "tagline": {"en": "x", "hi-en": "x"},
            "free": True,
            "status": "live",
            "accent": "#000000",
            "accentDark": "#000000",
            "icon": "film",
            "langs": ["en", "hi-en"],
        }
        manifest = tmp_path / "packs.json"
        manifest.write_text(json.dumps([entry]), encoding="utf-8")
        (packs,) = load_packs_meta(path=manifest)
        assert packs.dir == tmp_path / "mypack"


# ---------------------------------------------------------------------------
# Pack content loading + validation
# ---------------------------------------------------------------------------


class TestValidatePackContent:
    """Tests for validate_pack_content()."""

    def test_valid_content_round_trips(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path)
        _write_pack_content(
            pack,
            {"en": _SAFE_SECRETS, "hi-en": _SAFE_SECRETS},
            {"en": _SAFE_CLUES, "hi-en": _SAFE_CLUES},
        )
        vocab_by_lang = {"en": _STUB_VOCAB, "hi-en": _STUB_VOCAB}
        result = validate_pack_content(pack, vocab_by_lang)
        assert result["en"] == (_SAFE_SECRETS, _SAFE_CLUES)
        assert result["hi-en"] == (_SAFE_SECRETS, _SAFE_CLUES)

    def test_secret_not_in_vocab_raises(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path)
        _write_pack_content(
            pack,
            {"en": ["notinvocab"], "hi-en": ["notinvocab"]},
            {"en": ["a clue"], "hi-en": ["a clue"]},
        )
        vocab_by_lang = {"en": _STUB_VOCAB, "hi-en": _STUB_VOCAB}
        with pytest.raises(ValueError, match="not in vocab"):
            validate_pack_content(pack, vocab_by_lang)

    def test_secret_clue_count_mismatch_raises(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path)
        _write_pack_content(
            pack,
            {"en": ["ocean", "tiger"], "hi-en": ["ocean", "tiger"]},
            {"en": ["only one clue"], "hi-en": ["only one clue"]},
        )
        vocab_by_lang = {"en": _STUB_VOCAB, "hi-en": _STUB_VOCAB}
        with pytest.raises(ValueError, match="count mismatch"):
            validate_pack_content(pack, vocab_by_lang)

    def test_secret_count_mismatch_across_langs_raises(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path)
        _write_pack_content(
            pack,
            {"en": ["ocean", "tiger"], "hi-en": ["ocean"]},
            {"en": ["clue one", "clue two"], "hi-en": ["clue one"]},
        )
        vocab_by_lang = {"en": _STUB_VOCAB, "hi-en": _STUB_VOCAB}
        with pytest.raises(ValueError, match="mismatch across langs"):
            validate_pack_content(pack, vocab_by_lang)

    def test_profane_secret_raises(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path)
        # "ass" is in vocab/profanity_en.txt per the real blocklist.
        _write_pack_content(
            pack,
            {"en": ["ass"], "hi-en": ["ass"]},
            {"en": ["a clue"], "hi-en": ["a clue"]},
        )
        vocab_by_lang = {"en": [*_STUB_VOCAB, "ass"], "hi-en": [*_STUB_VOCAB, "ass"]}
        with pytest.raises(ValueError, match="profanity blocklist"):
            validate_pack_content(pack, vocab_by_lang)

    def test_empty_content_is_valid(self, tmp_path: Path) -> None:
        """Comment-only content files (0 secrets) validate successfully."""
        pack = _make_stub_pack(tmp_path)
        _write_pack_content(pack, {"en": [], "hi-en": []}, {"en": [], "hi-en": []})
        vocab_by_lang = {"en": _STUB_VOCAB, "hi-en": _STUB_VOCAB}
        result = validate_pack_content(pack, vocab_by_lang)
        assert result["en"] == ([], [])
        assert result["hi-en"] == ([], [])


# ---------------------------------------------------------------------------
# build_pack_payload / write_pack_payload schema + namespacing
# ---------------------------------------------------------------------------


class TestBuildPackPayload:
    """Tests for payload.build_pack_payload()."""

    def test_pack_and_idx_fields_present(self) -> None:
        p = build_pack_payload(
            _STUB_VOCAB, _STUB_MATRIX, "ocean", "en", "bollywood-001", "bollywood", 1
        )
        assert p["pack"] == "bollywood"
        assert p["idx"] == 1

    def test_date_field_carries_opaque_key(self) -> None:
        p = build_pack_payload(
            _STUB_VOCAB, _STUB_MATRIX, "ocean", "en", "bollywood-001", "bollywood", 1
        )
        assert p["date"] == "bollywood-001"

    def test_schema_matches_daily_v3_plus_pack_fields(self) -> None:
        daily = build_payload(_STUB_VOCAB, _STUB_MATRIX, "ocean", "en", date(2026, 6, 12))
        pack = build_pack_payload(
            _STUB_VOCAB, _STUB_MATRIX, "ocean", "en", "bollywood-001", "bollywood", 1
        )
        assert set(pack.keys()) == set(daily.keys()) | {"pack", "idx"}

    def test_decode_secret_round_trips(self) -> None:
        p = build_pack_payload(
            _STUB_VOCAB, _STUB_MATRIX, "tiger", "en", "bollywood-002", "bollywood", 2
        )
        assert decode_secret(p) == "tiger"

    def test_pack_salt_differs_from_daily_salt_for_same_word(self) -> None:
        """
        A pack puzzle's opaque key ("bollywood-001") never collides with a
        real ISO date string, so its salt/hashes never coincide with a daily
        puzzle's for the same secret word.
        """
        daily = build_payload(_STUB_VOCAB, _STUB_MATRIX, "ocean", "en", date(2026, 6, 12))
        pack = build_pack_payload(
            _STUB_VOCAB, _STUB_MATRIX, "ocean", "en", "bollywood-001", "bollywood", 1
        )
        assert daily["salt"] != pack["salt"]
        assert daily["date"] != pack["date"]


class TestBuildOnePack:
    """Tests for build_packs.build_one_pack() — full pack build + write."""

    def _vocab_and_matrix(self) -> tuple[dict[str, list[str]], dict[str, np.ndarray]]:
        vocab_by_lang = {"en": _STUB_VOCAB, "hi-en": _STUB_VOCAB}
        matrix_by_lang = {"en": _STUB_MATRIX, "hi-en": _STUB_MATRIX}
        return vocab_by_lang, matrix_by_lang

    def test_writes_namespaced_files(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path / "content")
        _write_pack_content(
            pack,
            {"en": _SAFE_SECRETS, "hi-en": _SAFE_SECRETS},
            {"en": _SAFE_CLUES, "hi-en": _SAFE_CLUES},
        )
        vocab_by_lang, matrix_by_lang = self._vocab_and_matrix()
        out_dir = tmp_path / "out"

        count, violation = build_one_pack(
            pack, ["en", "hi-en"], vocab_by_lang, matrix_by_lang, out_dir, strict_sizes=False
        )

        assert count == 3
        assert violation is False
        for lang in ("en", "hi-en"):
            for nnn in ("001", "002", "003"):
                assert (out_dir / "packs" / "testpack" / lang / f"{nnn}.json.gz").exists()

    def test_payload_content_matches_index(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path / "content")
        _write_pack_content(
            pack,
            {"en": _SAFE_SECRETS, "hi-en": _SAFE_SECRETS},
            {"en": _SAFE_CLUES, "hi-en": _SAFE_CLUES},
        )
        vocab_by_lang, matrix_by_lang = self._vocab_and_matrix()
        out_dir = tmp_path / "out"
        build_one_pack(
            pack, ["en", "hi-en"], vocab_by_lang, matrix_by_lang, out_dir, strict_sizes=False
        )

        gz_path = out_dir / "packs" / "testpack" / "en" / "002.json.gz"
        payload = json.loads(gzip.decompress(gz_path.read_bytes()))
        assert payload["pack"] == "testpack"
        assert payload["idx"] == 2
        assert payload["date"] == "testpack-002"
        assert decode_secret(payload) == "tiger"

    def test_rebuild_is_byte_identical(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path / "content")
        _write_pack_content(
            pack,
            {"en": _SAFE_SECRETS, "hi-en": _SAFE_SECRETS},
            {"en": _SAFE_CLUES, "hi-en": _SAFE_CLUES},
        )
        vocab_by_lang, matrix_by_lang = self._vocab_and_matrix()

        out1 = tmp_path / "out1"
        out2 = tmp_path / "out2"
        build_one_pack(pack, ["en", "hi-en"], vocab_by_lang, matrix_by_lang, out1, False)
        build_one_pack(pack, ["en", "hi-en"], vocab_by_lang, matrix_by_lang, out2, False)

        for lang in ("en", "hi-en"):
            for nnn in ("001", "002", "003"):
                b1 = (out1 / "packs" / "testpack" / lang / f"{nnn}.json.gz").read_bytes()
                b2 = (out2 / "packs" / "testpack" / lang / f"{nnn}.json.gz").read_bytes()
                assert b1 == b2, f"rebuild not byte-identical for {lang}/{nnn}"

    def test_spoiler_gate_rejects_leaking_clue(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path / "content")
        leaking_clues = ["The great blue tiger ocean", *_SAFE_CLUES[1:]]
        _write_pack_content(
            pack,
            {"en": _SAFE_SECRETS, "hi-en": _SAFE_SECRETS},
            {"en": leaking_clues, "hi-en": _SAFE_CLUES},
        )
        vocab_by_lang, matrix_by_lang = self._vocab_and_matrix()
        out_dir = tmp_path / "out"

        with pytest.raises(ValueError, match="leaks secret"):
            build_one_pack(
                pack, ["en", "hi-en"], vocab_by_lang, matrix_by_lang, out_dir, strict_sizes=False
            )

    def test_size_gate_enforced_under_strict_sizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import build_packs

        monkeypatch.setitem(build_packs.SIZE_TARGETS, "en", 1)  # impossible to satisfy
        monkeypatch.setitem(build_packs.SIZE_TARGETS, "hi-en", 1)

        pack = _make_stub_pack(tmp_path / "content")
        _write_pack_content(
            pack,
            {"en": _SAFE_SECRETS, "hi-en": _SAFE_SECRETS},
            {"en": _SAFE_CLUES, "hi-en": _SAFE_CLUES},
        )
        vocab_by_lang, matrix_by_lang = self._vocab_and_matrix()
        out_dir = tmp_path / "out"

        count, violation = build_one_pack(
            pack, ["en", "hi-en"], vocab_by_lang, matrix_by_lang, out_dir, strict_sizes=True
        )
        assert count == 3
        assert violation is True

    def test_non_live_pack_builds_to_count_zero(self, tmp_path: Path) -> None:
        pack = _make_stub_pack(tmp_path / "content")
        pack = PackMeta(**{**pack.__dict__, "status": "coming_soon"})
        _write_pack_content(
            pack,
            {"en": _SAFE_SECRETS, "hi-en": _SAFE_SECRETS},
            {"en": _SAFE_CLUES, "hi-en": _SAFE_CLUES},
        )
        vocab_by_lang, matrix_by_lang = self._vocab_and_matrix()
        out_dir = tmp_path / "out"

        count, violation = build_one_pack(
            pack, ["en", "hi-en"], vocab_by_lang, matrix_by_lang, out_dir, strict_sizes=False
        )
        assert count == 0
        assert violation is False
        assert not (out_dir / "packs").exists()

    def test_empty_content_pack_builds_to_count_zero_no_files_no_crash(
        self, tmp_path: Path
    ) -> None:
        """A live pack with comment-only content (bollywood's current state) is graceful."""
        pack = _make_stub_pack(tmp_path / "content")
        _write_pack_content(pack, {"en": [], "hi-en": []}, {"en": [], "hi-en": []})
        vocab_by_lang, matrix_by_lang = self._vocab_and_matrix()
        out_dir = tmp_path / "out"

        count, violation = build_one_pack(
            pack, ["en", "hi-en"], vocab_by_lang, matrix_by_lang, out_dir, strict_sizes=False
        )
        assert count == 0
        assert violation is False
        assert not (out_dir / "packs").exists()


# ---------------------------------------------------------------------------
# Inline spoiler gate predicate
# ---------------------------------------------------------------------------


class TestClueLeakReason:
    """Unit tests for build_packs.clue_leak_reason()."""

    def test_safe_clue_returns_none(self) -> None:
        assert clue_leak_reason("Stripes stalk the jungle undergrowth", "tiger", []) is None

    def test_direct_substring_detected(self) -> None:
        assert clue_leak_reason("The mighty tiger prowls", "tiger", []) is not None

    def test_morphological_variant_detected(self) -> None:
        assert clue_leak_reason("Where the oceans meet the sky", "ocean", []) is not None

    def test_alias_leak_detected(self) -> None:
        assert clue_leak_reason("It falls as baarish outside", "barish", ["baarish"]) is not None


# ---------------------------------------------------------------------------
# Daily build path unaffected by the payload.py refactor
# ---------------------------------------------------------------------------


class TestDailyPathUnaffected:
    """
    Guards against regressions in the daily build path introduced while adding
    build_pack_payload — the shared core builder must produce byte-identical
    daily output.
    """

    def test_derive_salt_recipe_unchanged(self) -> None:
        """derive_salt's hash recipe must be untouched by the pack salt helper."""
        raw = f"2026-06-12en{SALT_SUFFIX}"
        expected = hashlib.sha1(raw.encode()).hexdigest()[:16]  # noqa: S324
        assert derive_salt(date(2026, 6, 12), "en") == expected
        assert derive_salt(date(2026, 6, 12), "en") == "7ca5996a071e2723"

    def test_derive_salt_for_key_uses_same_suffix_different_recipe(self) -> None:
        """derive_salt_for_key shares SALT_SUFFIX but keys on an opaque string, not a date."""
        raw = f"bollywood-001en{SALT_SUFFIX}"
        expected = hashlib.sha1(raw.encode()).hexdigest()[:16]  # noqa: S324
        assert derive_salt_for_key("bollywood-001", "en") == expected

    def test_daily_payload_golden_gzip_hash(self, tmp_path: Path) -> None:
        """
        Byte-for-byte regression guard: a fixed stub vocab/date/secret must
        always compress to the same gzip bytes. This hash was captured against
        the current (post-refactor) code and must never change for this input.

        Updated for the maxGuesses formula change (fixed `par + 6` offset ->
        `max_guesses_for_par`, see rival.py) — the golden byte string
        necessarily changes because maxGuesses is baked into the payload,
        but the guard's INTENT (catch unintended byte drift) is unchanged.
        """
        p = build_payload(_STUB_VOCAB, _STUB_MATRIX, "ocean", "en", date(2026, 6, 12))
        out_path = write_payload(p, tmp_path, "en", date(2026, 6, 12))
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        assert digest == "ba1fdc65ffaef08dae8e151da6964a6e7e2b2df73be10777b903648e7919ee6d"

    def test_daily_payload_has_no_pack_fields(self) -> None:
        """Daily payloads must never carry the pack-only "pack"/"idx" fields."""
        p = build_payload(_STUB_VOCAB, _STUB_MATRIX, "ocean", "en", date(2026, 6, 12))
        assert "pack" not in p
        assert "idx" not in p
