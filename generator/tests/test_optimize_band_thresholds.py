from __future__ import annotations

"""
Tests for evals/finetune/optimize_band_thresholds.py -- WORKSTREAM 3
(spec-metrics-ceiling-calibration.md) deterministic band-threshold search.

Covers: parity with the real rival.band_for_rank at CURRENT_PARAMS, the
regression-floor fixed/broken accounting, the grid search finding a
known-optimal threshold on a synthetic fixture built so the answer is known
by construction, and structural checks on the bootstrap-CI and
band-reachability helpers.
"""

import pytest

from evals.finetune.optimize_band_thresholds import (
    CURRENT_PARAMS,
    band_for_rank_params,
    band_reachability,
    bootstrap_per_band_pr_ci,
    grid_search,
    macro_tier_accuracy,
    recompute_bands,
    regression_floor,
    tier_accuracy,
)
from packs import load_pack_secrets, load_packs_meta
from rival import band_for_rank
from schedule import load_schedule

# ---------------------------------------------------------------------------
# band_for_rank_params parity with the real production rival.band_for_rank
# ---------------------------------------------------------------------------


class TestBandForRankParamsParity:
    @pytest.mark.parametrize(
        "n",
        [55000, 10495, 1000, 100],
    )
    def test_matches_rival_band_for_rank_at_current_params(self, n: int) -> None:
        # Dense sweep across every boundary-adjacent rank plus a spread of
        # interior ranks -- CURRENT_PARAMS must reproduce rival.band_for_rank
        # byte-for-byte, since it is the same formula in parameterised form.
        sample_ranks = sorted(
            {1, 2, 49, 50, 51, 499, 500, 501, 1049, 1050, 1051}
            | {max(1, n // 4), max(1, n // 2), n - 1}
        )
        for rank in sample_ranks:
            if rank > n:
                continue
            assert band_for_rank_params(rank, n, CURRENT_PARAMS) == band_for_rank(rank, n), (
                f"mismatch at rank={rank}, n={n}"
            )


# ---------------------------------------------------------------------------
# tier_accuracy / macro_tier_accuracy -- hand-computed toy fixture
# ---------------------------------------------------------------------------


def _toy_records() -> list[dict]:
    # near: 2 records, 1 correct (band 1 in [1,2]); mid: 2 records, 0
    # correct; far: 2 records, 2 correct.
    return [
        {
            "secret": "s",
            "word": "a",
            "tier": "near",
            "actual_rank": 10,
            "expected_bands": [1, 2],
        },
        {
            "secret": "s",
            "word": "b",
            "tier": "near",
            "actual_rank": 5000,
            "expected_bands": [1, 2],
        },
        {
            "secret": "s",
            "word": "c",
            "tier": "mid",
            "actual_rank": 5000,
            "expected_bands": [3],
        },
        {
            "secret": "s",
            "word": "d",
            "tier": "mid",
            "actual_rank": 9000,
            "expected_bands": [3],
        },
        {
            "secret": "s",
            "word": "e",
            "tier": "far",
            "actual_rank": 3000,
            "expected_bands": [4, 5],
        },
        {
            "secret": "s",
            "word": "f",
            "tier": "far",
            "actual_rank": 9500,
            "expected_bands": [4, 5],
        },
    ]


class TestTierAccuracy:
    def test_hand_computed_accuracy(self) -> None:
        n = 10000
        records = recompute_bands(_toy_records(), n, params=None)
        acc = tier_accuracy(records)
        # n=10000: hot_max=max(500,100)=500, warm_max=max(900,500)=900,
        # cold_max=int(10000*0.25)=2500 -- every rank here (5000/9000/3000/
        # 9500) is > cold_max, so all land in freezing(5); only rank=10
        # lands in scorching(1) (verified directly via rival.band_for_rank).
        # near: rank10->scorching(1, in [1,2])=correct; rank5000->
        # freezing(5, not in [1,2])=wrong -> 0.5
        assert acc["near"] == pytest.approx(0.5)
        # mid: rank5000->freezing(5, not in [3])=wrong; rank9000->
        # freezing(5, not in [3])=wrong -> 0.0
        assert acc["mid"] == pytest.approx(0.0)
        # far: rank3000->freezing(5, in [4,5])=correct; rank9500->
        # freezing(5, in [4,5])=correct -> 1.0
        assert acc["far"] == pytest.approx(1.0)

    def test_macro_tier_accuracy_is_unweighted_mean(self) -> None:
        n = 10000
        records = recompute_bands(_toy_records(), n, params=None)
        macro = macro_tier_accuracy(records)
        assert macro == pytest.approx((0.5 + 0.0 + 1.0) / 3)

    def test_none_tier_excluded_from_macro(self) -> None:
        # Drop all "far" records -- macro should average only near/mid.
        recs = [r for r in _toy_records() if r["tier"] != "far"]
        records = recompute_bands(recs, 10000, params=None)
        acc = tier_accuracy(records)
        assert acc["far"] is None
        macro = macro_tier_accuracy(records)
        assert macro == pytest.approx((0.5 + 0.0) / 2)


# ---------------------------------------------------------------------------
# regression_floor -- fixed/broken accounting
# ---------------------------------------------------------------------------


class TestRegressionFloor:
    def test_fixed_and_broken_counted_correctly(self) -> None:
        n = 10000
        recs = _toy_records()
        baseline = recompute_bands(recs, n, params=None)
        # Candidate: widen warm_max enormously so mid's rank=5000 record
        # (currently cold/wrong) becomes warm/correct -- a "fix". But this
        # ALSO swallows far's rank=3000 record (currently cold/correct)
        # into warm -- a "break".
        wide_warm: dict = dict(CURRENT_PARAMS)
        wide_warm["warm_floor"] = 6000
        candidate = recompute_bands(recs, n, params=wide_warm)
        rf = regression_floor(baseline, candidate)
        assert rf["fixed"] == 1
        assert rf["broken"] == 1
        assert rf["net"] == 0
        assert rf["fixed_by_tier"]["mid"] == 1
        assert rf["broken_by_tier"]["far"] == 1
        outcomes = {(d["outcome"], d["word"]) for d in rf["detail"]}
        assert ("fixed", "c") in outcomes
        assert ("broken", "e") in outcomes

    def test_no_change_zero_fixed_zero_broken(self) -> None:
        n = 10000
        recs = _toy_records()
        baseline = recompute_bands(recs, n, params=None)
        candidate = recompute_bands(recs, n, params=dict(CURRENT_PARAMS))
        rf = regression_floor(baseline, candidate)
        assert rf["fixed"] == 0
        assert rf["broken"] == 0
        assert rf["net"] == 0

    def test_misaligned_lists_raise(self) -> None:
        n = 10000
        recs = _toy_records()
        baseline = recompute_bands(recs, n, params=None)
        shuffled = recompute_bands(list(reversed(recs)), n, params=None)
        with pytest.raises(AssertionError):
            regression_floor(baseline, shuffled)


# ---------------------------------------------------------------------------
# grid_search -- synthetic fixture where the optimal warm_floor is known by
# construction, so the search's answer can be checked exactly.
# ---------------------------------------------------------------------------


def _synthetic_grid_fixture() -> tuple[list[dict], int]:
    """n=10000, current (shipped, post-WS3) warm_max = max(1050, 500) = 1050.
    Construct:
      - 5 mid-tier records at rank 1200 (currently cold/wrong; become
        warm/correct for any warm_floor >= 1200).
      - 2 far-tier records at rank 1700 (currently cold/correct; become
        warm/WRONG for any warm_floor >= 1700).
    By construction, the optimal net (fixed-broken) is achieved at any
    warm_floor in [1200, 1699]: net=+5 fixed/0 broken. Any warm_floor
    >= 1700 costs the 2 far records for no further mid gain (net=+3).
    """
    n = 10000
    records: list[dict] = []
    for i in range(5):
        records.append(
            {
                "secret": "s",
                "word": f"mid{i}",
                "tier": "mid",
                "actual_rank": 1200,
                "expected_bands": [3],
            }
        )
    for i in range(2):
        records.append(
            {
                "secret": "s",
                "word": f"far{i}",
                "tier": "far",
                "actual_rank": 1700,
                "expected_bands": [4, 5],
            }
        )
    return records, n


class TestGridSearchKnownOptimum:
    def test_finds_the_zero_broken_optimum(self) -> None:
        records, n = _synthetic_grid_fixture()
        results = grid_search(
            records,
            n,
            hot_floors=[500],
            hot_fracs=[0.01],
            warm_floors=[1050, 1100, 1200, 1699, 1700, 1800, 2200],
            warm_fracs=[0.05],
        )
        best = results[0]
        assert best["net"] == 5
        assert best["fixed"] == 5
        assert best["broken"] == 0
        assert 1200 <= best["params"]["warm_floor"] <= 1699

    def test_overshooting_the_boundary_costs_net(self) -> None:
        records, n = _synthetic_grid_fixture()
        results = grid_search(
            records,
            n,
            hot_floors=[500],
            hot_fracs=[0.01],
            warm_floors=[1800],
            warm_fracs=[0.05],
        )
        row = results[0]
        assert row["fixed"] == 5
        assert row["broken"] == 2
        assert row["net"] == 3

    def test_results_sorted_best_first(self) -> None:
        records, n = _synthetic_grid_fixture()
        results = grid_search(
            records,
            n,
            hot_floors=[500],
            hot_fracs=[0.01],
            warm_floors=[1050, 1200, 1800, 2200],
            warm_fracs=[0.05],
        )
        nets = [r["net"] for r in results]
        assert nets == sorted(nets, reverse=True)


# ---------------------------------------------------------------------------
# bootstrap_per_band_pr_ci -- structural checks (real shipped data, small
# n_boot for test speed -- correctness of the underlying per-band P/R math
# is already covered by test_topheavy_metrics.py; this only checks the
# bootstrap wiring/shape).
# ---------------------------------------------------------------------------


class TestBootstrapPerBandPRCI:
    def test_shape_and_bands(self) -> None:
        from evals.finetune.optimize_band_thresholds import load_shipped_records

        records, n = load_shipped_records()
        baseline = recompute_bands(records, n, params=None)
        ci = bootstrap_per_band_pr_ci(baseline, n_boot=50, seed=42)
        assert set(ci.keys()) == {"win", "scorching", "hot", "warm", "cold", "freezing"}
        for _band, leaf in ci.items():
            assert "precision_point" in leaf
            assert "recall_point" in leaf
            assert "n_predicted" in leaf
            assert "n_expected" in leaf

    def test_deterministic_given_seed(self) -> None:
        from evals.finetune.optimize_band_thresholds import load_shipped_records

        records, n = load_shipped_records()
        baseline = recompute_bands(records, n, params=None)
        ci1 = bootstrap_per_band_pr_ci(baseline, n_boot=50, seed=7)
        ci2 = bootstrap_per_band_pr_ci(baseline, n_boot=50, seed=7)
        assert ci1 == ci2


# ---------------------------------------------------------------------------
# band_reachability -- real hi-en puzzle universe, small n_sims for speed.
# ---------------------------------------------------------------------------


class TestBandReachability:
    def test_current_thresholds_all_bands_reachable(self) -> None:
        n = 10495
        result = band_reachability(CURRENT_PARAMS, n, n_sims=10, seed=42)
        assert result["all_bands_reachable"] is True
        assert result["unreached_bands"] == []
        # Derived, not hard-coded: the universe is the hi-en daily schedule plus every LIVE
        # hi-en pack, so it grows whenever a pack goes live (it was 118, then 143). A literal
        # here broke the suite the first time a pack shipped without anyone touching this code.
        expected = len(load_schedule("hi-en")) + sum(
            len(load_pack_secrets(p, "hi-en"))
            for p in load_packs_meta()
            if p.status == "live" and "hi-en" in p.langs
        )
        assert expected > len(load_schedule("hi-en"))  # at least one live pack is counted
        assert result["n_puzzles"] == expected

    def test_pathological_params_can_starve_a_band(self) -> None:
        # Sanity check the detector itself: a warm_floor wide enough to
        # swallow the whole vocab makes "cold"/"freezing" unreachable --
        # confirms unreached_bands isn't vacuously empty by construction.
        n = 10495
        starved: dict = dict(CURRENT_PARAMS)
        starved["warm_floor"] = n  # warm consumes everything past hot_max
        result = band_reachability(starved, n, n_sims=10, seed=42)
        assert "cold" in result["unreached_bands"]
        assert "freezing" in result["unreached_bands"]
        assert result["all_bands_reachable"] is False
