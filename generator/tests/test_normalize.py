from __future__ import annotations

"""
Unit tests for the romanized-Hindi normalization module.

Covers:
  - normalize() folding rules (deterministic, order-sensitive)
  - canonical_for() alias resolution
  - All fixture cases from evals/fixtures_normalization.json
  - Byte-identity check between evals and app fixture copies
"""

import json
from pathlib import Path

import pytest

from normalize import canonical_for, normalize

_FIXTURE_PATH = Path(__file__).parent.parent / "evals" / "fixtures_normalization.json"
_APP_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent / "app" / "test" / "fixtures" / "normalization_fixture.json"
)


# ---------------------------------------------------------------------------
# normalize() rule unit tests
# ---------------------------------------------------------------------------


class TestNormalizeRules:
    """Test each normalization rule in isolation and combined."""

    def test_lowercase_and_strip(self) -> None:
        assert normalize("  BAARISH  ") == "barish"

    def test_chh_to_ch(self) -> None:
        assert normalize("chhata") == "chata"

    def test_chh_to_ch_then_aa_to_a(self) -> None:
        # "chhaata": chh→ch first → "chaata" → aa→a → "chata"
        assert normalize("chhaata") == "chata"

    def test_aa_to_a(self) -> None:
        assert normalize("baarish") == "barish"

    def test_aa_to_a_multiple_occurrences(self) -> None:
        # "chaand" → "chand"
        assert normalize("chaand") == "chand"

    def test_ee_to_i(self) -> None:
        assert normalize("bageecha") == "bagicha"

    def test_ee_to_i_multiple(self) -> None:
        assert normalize("tasveer") == "tasvir"

    def test_oo_to_u(self) -> None:
        assert normalize("khushboo") == "khushbu"

    def test_oo_to_u_multiple(self) -> None:
        # "gooool" (hypothetical) — each oo → u
        assert normalize("momboo") == "mombu"

    def test_no_change_on_already_canonical(self) -> None:
        # "mombatti" has no doubled vowels or chh
        assert normalize("mombatti") == "mombatti"

    def test_uppercase_input_lowercased(self) -> None:
        assert normalize("GAANA") == "gana"

    def test_mixed_case_with_rules(self) -> None:
        assert normalize("KHUSHBoo") == "khushbu"

    def test_rule_order_chh_before_aa(self) -> None:
        # If chh→ch is applied first and aa→a second, result differs from reverse order.
        # "chhaana": chh→ch → "chaana" → aa→a → "chana"
        assert normalize("chhaana") == "chana"

    def test_empty_string(self) -> None:
        assert normalize("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize("   ") == ""

    def test_no_rule_fires_on_plain_ascii(self) -> None:
        assert normalize("jungle") == "jungle"


# ---------------------------------------------------------------------------
# canonical_for() alias resolution tests
# ---------------------------------------------------------------------------


class TestCanonicalFor:
    """Test alias-file resolution on top of normalization."""

    def test_alias_razai(self) -> None:
        assert canonical_for("razai") == "razaai"

    def test_alias_rajai(self) -> None:
        assert canonical_for("rajai") == "razaai"

    def test_alias_barish(self) -> None:
        assert canonical_for("barish") == "baarish"

    def test_alias_gyan(self) -> None:
        assert canonical_for("gyan") == "gyaan"

    def test_normalize_then_alias_gana(self) -> None:
        # "GANA  " → normalize → "gana" → alias → "gaana"
        assert canonical_for("GANA  ") == "gaana"

    def test_alias_mombati(self) -> None:
        assert canonical_for("mombati") == "mombatti"

    def test_alias_hasi(self) -> None:
        assert canonical_for("hasi") == "hansi"

    def test_no_alias_needed_khushbu(self) -> None:
        # "khushboo" → normalize → "khushbu" (no alias needed; normalize gets there)
        assert canonical_for("khushboo") == "khushbu"

    def test_custom_alias_map_injection(self) -> None:
        """canonical_for accepts an explicit alias_map to avoid file dependency."""
        custom = {"testword": "canonical"}
        assert canonical_for("testword", alias_map=custom) == "canonical"
        assert canonical_for("otherword", alias_map=custom) == "otherword"


# ---------------------------------------------------------------------------
# All fixture cases (contract test)
# ---------------------------------------------------------------------------


def _load_fixture_cases() -> list[tuple[str, str]]:
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return [(case["input"], case["canonical"]) for case in data["cases"]]


@pytest.mark.parametrize("inp,expected", _load_fixture_cases())
def test_fixture_case_resolves(inp: str, expected: str) -> None:
    """Every case in fixtures_normalization.json must resolve to its canonical."""
    result = canonical_for(inp)
    assert result == expected, f"canonical_for({inp!r}) returned {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# Byte-identity check between evals and app fixture copies
# ---------------------------------------------------------------------------


def test_app_fixture_is_byte_identical_to_evals_fixture() -> None:
    """
    app/test/fixtures/normalization_fixture.json must be a byte-for-byte copy
    of evals/fixtures_normalization.json.

    Skips cleanly when the app/ directory is absent (e.g. CI-only generator run).
    """
    if not _APP_FIXTURE_PATH.exists():
        pytest.skip(f"app fixture not found: {_APP_FIXTURE_PATH}")

    generator_bytes = _FIXTURE_PATH.read_bytes()
    app_bytes = _APP_FIXTURE_PATH.read_bytes()
    assert generator_bytes == app_bytes, (
        "app/test/fixtures/normalization_fixture.json differs from "
        "evals/fixtures_normalization.json — run: "
        "cp evals/fixtures_normalization.json "
        "../app/test/fixtures/normalization_fixture.json"
    )
