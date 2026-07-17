from __future__ import annotations

"""
Tests for the deterministic rival-path solver (rival.py).

Covers: determinism, no-word-leak, band correctness, tier diversity,
path termination, par computation, payload schema integration.
"""

import json
from datetime import date, timedelta

import numpy as np
import pytest

from payload import build_payload
from rival import _rival_seed, band_for_rank, generate_rival_data, max_guesses_for_par

# ---------------------------------------------------------------------------
# Shared stub data (mirrors test_payload.py setup)
# ---------------------------------------------------------------------------

_STUB_VOCAB = [
    "ocean", "sea", "mountain", "rain", "book",
    "music", "friend", "bread", "fire", "flower",
]
_STUB_DIM = 4
_rng = np.random.default_rng(42)
_raw = _rng.standard_normal((len(_STUB_VOCAB), _STUB_DIM)).astype(np.float32)
_norms = np.linalg.norm(_raw, axis=1, keepdims=True)
_STUB_MATRIX = (_raw / _norms).astype(np.float32)

_PUZZLE_DATE = date(2026, 6, 12)
_SECRET = "ocean"
_LANG = "en"
_N = len(_STUB_VOCAB)


@pytest.fixture()
def rival_data() -> tuple[dict, int]:
    return generate_rival_data(_N, _SECRET, _PUZZLE_DATE.isoformat())


class TestBandForRank:
    """Verify band_for_rank() mirrors Dart thresholds exactly."""

    def test_rank_1_is_win(self) -> None:
        assert band_for_rank(1, 55000) == 0

    def test_scorching_boundary(self) -> None:
        n = 55000
        # max(50, n*0.001) = 55 → rank 55 = scorching, rank 56 = hot
        assert band_for_rank(55, n) == 1
        assert band_for_rank(56, n) == 2

    def test_hot_boundary(self) -> None:
        n = 55000
        # max(500, n*0.01) = 550 → rank 550 = hot, rank 551 = warm
        assert band_for_rank(550, n) == 2
        assert band_for_rank(551, n) == 3

    def test_warm_boundary(self) -> None:
        n = 55000
        # n*0.05 = 2750 → rank 2750 = warm, rank 2751 = cold
        assert band_for_rank(2750, n) == 3
        assert band_for_rank(2751, n) == 4

    def test_cold_boundary(self) -> None:
        n = 55000
        # n*0.25 = 13750 → rank 13750 = cold, rank 13751 = freezing
        assert band_for_rank(13750, n) == 4
        assert band_for_rank(13751, n) == 5

    def test_small_vocab_scorching_floor(self) -> None:
        # For n=100: max(50, 100*0.001)=50; rank 50=scorching, rank 51=hot
        assert band_for_rank(50, 100) == 1
        assert band_for_rank(51, 100) == 2

    def test_small_vocab_hot_floor(self) -> None:
        # For n=1000: hot_max = max(500, 1000*0.01) = 500; rank 500 = hot.
        # warm_max = int(1000*0.05) = 50 (already covered by hot), so
        # rank 501 falls past hot_max and past warm/cold thresholds.
        # cold_max = int(1000*0.25) = 250; 501 > 250 → freezing (5).
        assert band_for_rank(500, 1000) == 2
        assert band_for_rank(501, 1000) == 5


class TestRivalSeed:
    """Verify seed derivation is deterministic and secret-dependent."""

    def test_seed_is_20_bytes(self) -> None:
        seed = _rival_seed("ocean", "2026-06-12")
        assert len(seed) == 20

    def test_seed_deterministic(self) -> None:
        s1 = _rival_seed("ocean", "2026-06-12")
        s2 = _rival_seed("ocean", "2026-06-12")
        assert s1 == s2

    def test_different_secrets_different_seeds(self) -> None:
        s1 = _rival_seed("ocean", "2026-06-12")
        s2 = _rival_seed("river", "2026-06-12")
        assert s1 != s2

    def test_different_dates_different_seeds(self) -> None:
        s1 = _rival_seed("ocean", "2026-06-12")
        s2 = _rival_seed("ocean", "2026-06-13")
        assert s1 != s2


class TestGenerateRivalData:
    """Core tests for generate_rival_data()."""

    def test_returns_three_tiers(self, rival_data: tuple[dict, int]) -> None:
        rival, par = rival_data
        assert set(rival.keys()) == {"even", "chill", "sharp"}

    def test_each_tier_has_path_and_solve_at(self, rival_data: tuple[dict, int]) -> None:
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            assert "path" in tier_dict, f"{tier_name} missing 'path'"
            assert "solveAt" in tier_dict, f"{tier_name} missing 'solveAt'"

    def test_par_equals_even_solve_at(self, rival_data: tuple[dict, int]) -> None:
        rival, par = rival_data
        assert par == rival["even"]["solveAt"]

    def test_path_ends_at_rank_one(self, rival_data: tuple[dict, int]) -> None:
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            path = tier_dict["path"]
            assert path[-1]["rank"] == 1, f"{tier_name} path does not end at rank 1"

    def test_solve_at_equals_path_length(self, rival_data: tuple[dict, int]) -> None:
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            assert tier_dict["solveAt"] == len(tier_dict["path"]), (
                f"{tier_name}: solveAt != len(path)"
            )

    def test_path_steps_have_rank_and_band(self, rival_data: tuple[dict, int]) -> None:
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            for i, step in enumerate(tier_dict["path"]):
                assert "rank" in step, f"{tier_name}[{i}] missing 'rank'"
                assert "band" in step, f"{tier_name}[{i}] missing 'band'"

    def test_path_step_types_are_int(self, rival_data: tuple[dict, int]) -> None:
        """All path values must be integers (no word strings)."""
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            for i, step in enumerate(tier_dict["path"]):
                assert isinstance(step["rank"], int), (
                    f"{tier_name}[{i}].rank is not int: {step['rank']!r}"
                )
                assert isinstance(step["band"], int), (
                    f"{tier_name}[{i}].band is not int: {step['band']!r}"
                )

    def test_rank_values_in_valid_range(self, rival_data: tuple[dict, int]) -> None:
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            for i, step in enumerate(tier_dict["path"]):
                assert 1 <= step["rank"] <= _N, (
                    f"{tier_name}[{i}].rank={step['rank']} out of [1, {_N}]"
                )

    def test_band_values_in_valid_range(self, rival_data: tuple[dict, int]) -> None:
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            for i, step in enumerate(tier_dict["path"]):
                assert 0 <= step["band"] <= 5, (
                    f"{tier_name}[{i}].band={step['band']} out of [0, 5]"
                )

    def test_final_step_band_is_win(self, rival_data: tuple[dict, int]) -> None:
        """Last step has rank 1 and band 0 (win)."""
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            last = tier_dict["path"][-1]
            assert last["rank"] == 1
            assert last["band"] == 0, f"{tier_name} last step band != 0 (win)"

    def test_determinism_across_calls(self) -> None:
        """Same inputs must produce byte-identical output."""
        r1, p1 = generate_rival_data(_N, _SECRET, _PUZZLE_DATE.isoformat())
        r2, p2 = generate_rival_data(_N, _SECRET, _PUZZLE_DATE.isoformat())
        assert p1 == p2
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    def test_different_secrets_produce_different_paths(self) -> None:
        # Use a larger vocab so path shapes diverge meaningfully between seeds.
        # With n=10 the paths can collide by chance; n=1000 avoids this.
        n_large = 1000
        r1, _ = generate_rival_data(n_large, "ocean", _PUZZLE_DATE.isoformat())
        r2, _ = generate_rival_data(n_large, "sea", _PUZZLE_DATE.isoformat())
        assert json.dumps(r1["even"]["path"]) != json.dumps(r2["even"]["path"])

    def test_tiers_produce_different_paths(self, rival_data: tuple[dict, int]) -> None:
        rival, _ = rival_data
        even_path = json.dumps(rival["even"]["path"])
        chill_path = json.dumps(rival["chill"]["path"])
        sharp_path = json.dumps(rival["sharp"]["path"])
        assert even_path != chill_path
        assert even_path != sharp_path

    def test_path_length_within_bounds(self, rival_data: tuple[dict, int]) -> None:
        rival, _ = rival_data
        for tier_name, tier_dict in rival.items():
            length = len(tier_dict["path"])
            assert 1 <= length <= 41, (
                f"{tier_name} path length {length} out of expected range [1, 41]"
            )

    def test_par_positive(self, rival_data: tuple[dict, int]) -> None:
        _, par = rival_data
        assert par >= 1


class TestNoWordLeak:
    """
    CRITICAL: rival paths must never expose vocabulary word strings.

    A word string in the rival payload would leak semantic proximity to the
    secret, violating spoiler safety. Only integers (rank + band ordinal)
    are permissible as values in the rival section.
    """

    def test_rival_exposes_no_vocab_words_as_strings(self) -> None:
        """No vocabulary word appears as a string value anywhere in rival JSON."""
        rival, _ = generate_rival_data(_N, _SECRET, _PUZZLE_DATE.isoformat())
        rival_json = json.dumps(rival)
        for word in _STUB_VOCAB:
            assert f'"{word}"' not in rival_json, (
                f"Word {word!r} found as a string in rival JSON — spoiler leak!"
            )

    def test_rival_step_values_are_all_integers(self) -> None:
        """Every value in every rival path step is an integer."""
        rival, _ = generate_rival_data(_N, _SECRET, _PUZZLE_DATE.isoformat())
        for tier_name, tier_dict in rival.items():
            for i, step in enumerate(tier_dict["path"]):
                for key, val in step.items():
                    assert isinstance(val, int), (
                        f"rival.{tier_name}.path[{i}].{key} = {val!r} is not int — "
                        f"only rank+band integers are allowed"
                    )

    def test_rival_section_in_full_payload_has_no_word_strings(self) -> None:
        """
        In a full build_payload() output, the 'rival' section must not contain
        any vocabulary word as a string value.
        """
        payload = build_payload(_STUB_VOCAB, _STUB_MATRIX, _SECRET, _LANG, _PUZZLE_DATE)
        rival_json = json.dumps(payload.get("rival", {}))
        for word in _STUB_VOCAB:
            assert f'"{word}"' not in rival_json, (
                f"Word {word!r} found in rival section of full payload"
            )


class TestPayloadSchemaV2:
    """Verify the full payload includes rival and parGuesses at v=2."""

    @pytest.fixture()
    def payload(self) -> dict:
        return build_payload(_STUB_VOCAB, _STUB_MATRIX, _SECRET, _LANG, _PUZZLE_DATE)

    def test_version_is_3(self, payload: dict) -> None:
        assert payload["v"] == 3

    def test_par_guesses_key_exists(self, payload: dict) -> None:
        assert "parGuesses" in payload

    def test_par_guesses_is_positive_int(self, payload: dict) -> None:
        par = payload["parGuesses"]
        assert isinstance(par, int) and par >= 1

    def test_rival_key_exists(self, payload: dict) -> None:
        assert "rival" in payload

    def test_rival_has_three_tiers(self, payload: dict) -> None:
        rival = payload["rival"]
        assert set(rival.keys()) == {"even", "chill", "sharp"}

    def test_rival_tiers_have_required_fields(self, payload: dict) -> None:
        for tier_name, tier_dict in payload["rival"].items():
            assert "path" in tier_dict, f"{tier_name} missing 'path'"
            assert "solveAt" in tier_dict, f"{tier_name} missing 'solveAt'"

    def test_rival_gzip_reproducibility(self, tmp_path) -> None:
        """Rival data does not break byte-reproducibility (mtime=0 gzip)."""
        from pathlib import Path

        from payload import write_payload

        out = Path(str(tmp_path))
        p = build_payload(_STUB_VOCAB, _STUB_MATRIX, _SECRET, _LANG, _PUZZLE_DATE)
        path1 = write_payload(p, out / "run1", _LANG, _PUZZLE_DATE)
        path2 = write_payload(p, out / "run2", _LANG, _PUZZLE_DATE)
        assert path1.read_bytes() == path2.read_bytes()

    def test_par_equals_even_solve_at(self, payload: dict) -> None:
        assert payload["parGuesses"] == payload["rival"]["even"]["solveAt"]


class TestMaxGuessesForPar:
    """Tests for the shared max_guesses_for_par helper (payload.py's and
    dimension5_winrate.py's maxGuesses formula, kept in one place so the two
    can't drift apart)."""

    def test_scales_with_par_above_floor(self) -> None:
        # par=10 -> round(10*1.5)=15, above the floor -> the multiplier wins.
        assert max_guesses_for_par(10) == 15

    def test_floor_applies_for_low_par(self) -> None:
        # par=4 -> round(4*1.5)=6, below the floor of 12 -> floor wins.
        assert max_guesses_for_par(4) == 12

    def test_always_exceeds_par(self) -> None:
        # A budget must always give the player more than the "expert" par
        # count, regardless of where par falls relative to the floor.
        for par in range(1, 20):
            assert max_guesses_for_par(par) > par

    def test_monotonic_non_decreasing(self) -> None:
        # A higher-par (harder) puzzle should never get a smaller budget
        # than an easier, lower-par one.
        values = [max_guesses_for_par(par) for par in range(1, 20)]
        # strict=False: values[1:] is deliberately one element shorter (a
        # sliding pairwise-comparison window), not a length mismatch bug.
        assert all(b >= a for a, b in zip(values, values[1:], strict=False))


class TestLargeVocabBehavior:
    """Sanity checks on a larger simulated vocab (n=55000)."""

    def test_large_vocab_paths_reach_rank_one(self) -> None:
        n = 55000
        rival, par = generate_rival_data(n, "ocean", "2026-06-15")
        for tier_name, tier_dict in rival.items():
            assert tier_dict["path"][-1]["rank"] == 1, (
                f"{tier_name} path did not reach rank 1 for n={n}"
            )

    def test_large_vocab_par_in_sane_range(self) -> None:
        """Par should land in [4, 16] after recalibration (target median 8–12)."""
        n = 55000
        _, par = generate_rival_data(n, "ocean", "2026-06-15")
        assert 4 <= par <= 16, f"Par={par} outside calibrated range [4, 16]"

    def test_large_vocab_no_word_leak(self) -> None:
        """No string values at all in rival section for large vocab."""
        n = 55000
        rival, _ = generate_rival_data(n, "ocean", "2026-06-15")
        # No alphabetic sequences quoted as JSON strings should appear in values
        # (keys like "rank", "band", "even", etc. are fine as keys, not values)
        for step in rival["even"]["path"]:
            for key, val in step.items():
                assert isinstance(val, int), f"Non-int value in large vocab rival: {key}={val!r}"


class TestTierSpreadGate:
    """
    Gate test: rival tier spreads must stay within calibrated bounds across
    the full 30-day puzzle window for both languages.

    Acceptance criteria:
      par (= even.solveAt) in [4, 16]
      chill.solveAt - par  in [2, 8]
      par - sharp.solveAt  in [1, 5]

    Calls generate_rival_data() with real schedule secrets; no embedding model
    is needed because rival paths are derived from the seed only.
    """

    _START = date(2026, 6, 12)
    _DAYS = 30

    def _window(self, lang: str, n: int) -> list[tuple[str, str, int]]:
        """Return list of (date_iso, secret, n) for every day in the window."""
        import os
        import sys

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from schedule import load_schedule, secret_for_date

        schedule = load_schedule(lang)
        return [
            (
                (self._START + timedelta(days=i)).isoformat(),
                secret_for_date(self._START + timedelta(days=i), lang, schedule),
                n,
            )
            for i in range(self._DAYS)
        ]

    @pytest.mark.parametrize("lang,n", [("en", 55000), ("hi-en", 10445)])
    def test_par_in_range_full_window(self, lang: str, n: int) -> None:
        """par ∈ [4, 16] for every puzzle in the 30-day window."""
        for d, secret, vocab_n in self._window(lang, n):
            _, par = generate_rival_data(vocab_n, secret, d)
            assert 4 <= par <= 16, (
                f"[{lang}] {d} secret={secret!r}: par={par} outside [4,16]"
            )

    @pytest.mark.parametrize("lang,n", [("en", 55000), ("hi-en", 10445)])
    def test_chill_spread_full_window(self, lang: str, n: int) -> None:
        """chill.solveAt - par ∈ [2, 8] for every puzzle."""
        for d, secret, vocab_n in self._window(lang, n):
            rival, par = generate_rival_data(vocab_n, secret, d)
            spread = rival["chill"]["solveAt"] - par
            assert 2 <= spread <= 8, (
                f"[{lang}] {d} secret={secret!r}: chill-par={spread} outside [2,8] (par={par})"
            )

    @pytest.mark.parametrize("lang,n", [("en", 55000), ("hi-en", 10445)])
    def test_sharp_spread_full_window(self, lang: str, n: int) -> None:
        """par - sharp.solveAt ∈ [1, 5] for every puzzle."""
        for d, secret, vocab_n in self._window(lang, n):
            rival, par = generate_rival_data(vocab_n, secret, d)
            spread = par - rival["sharp"]["solveAt"]
            assert 1 <= spread <= 5, (
                f"[{lang}] {d} secret={secret!r}: par-sharp={spread} outside [1,5] (par={par})"
            )
