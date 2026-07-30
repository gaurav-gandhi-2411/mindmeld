from __future__ import annotations

"""
Unit tests for the top-heavy ranking + band-calibration metric primitives
(evals/harness/metrics.py new functions) and their aggregation module
(evals/harness/topheavy.py) — spec-model-excellence.md WORKSTREAM A.

Hand-computed toy example (see spec-model-excellence.md task prompt /
PLAN.md for the derivation), secret "sec1", 4 judged records:
  A: tier=near, actual_rank=1   (relevance grade 2.0)
  B: tier=mid,  actual_rank=5   (relevance grade 1.0)
  C: tier=far,  actual_rank=3   (relevance grade 0.0)
  D: tier=near, actual_rank=20  (relevance grade 2.0)

DCG@10 = 3/log2(2) + 1/log2(6) + 0/log2(4) = 3.386853
IDCG@10 = 3/log2(2) + 3/log2(3) + 1/log2(4) + 0/log2(5) = 5.392789
NDCG@10 = 3.386853 / 5.392789 = 0.6280

DCG@50 = DCG@10 + 3/log2(21) = 4.069816
IDCG@50 == IDCG@10 (only 4 judged items) = 5.392789
NDCG@50 = 4.069816 / 5.392789 = 0.7547
"""

import math

import pytest

from evals.harness.metrics import (
    dcg_gain,
    expected_calibration_error,
    mean_reciprocal_rank,
    ndcg_from_judged,
    top_weighted_correlation,
)
from evals.harness.topheavy import (
    band_calibration_error,
    band_confusion_matrix,
    compute_nonsaturating_metrics,
    compute_nonsaturating_metrics_from_records,
    compute_topheavy_metrics,
    compute_topheavy_metrics_from_records,
    group_by_secret,
    per_band_precision_recall,
)

# ---------------------------------------------------------------------------
# Toy secret "sec1" fixture, reused across several tests.
# ---------------------------------------------------------------------------


def _toy_group() -> list[dict]:
    return [
        {"secret": "sec1", "word": "A", "tier": "near", "actual_rank": 1},
        {"secret": "sec1", "word": "B", "tier": "mid", "actual_rank": 5},
        {"secret": "sec1", "word": "C", "tier": "far", "actual_rank": 3},
        {"secret": "sec1", "word": "D", "tier": "near", "actual_rank": 20},
    ]


# ---------------------------------------------------------------------------
# dcg_gain / ndcg_from_judged
# ---------------------------------------------------------------------------


def test_dcg_gain_formula():
    assert dcg_gain(0.0) == pytest.approx(0.0)
    assert dcg_gain(1.0) == pytest.approx(1.0)
    assert dcg_gain(2.0) == pytest.approx(3.0)


def test_ndcg_from_judged_k10_hand_computed():
    ranked_judged = [(1, 2.0), (5, 1.0), (3, 0.0), (20, 2.0)]
    assert ndcg_from_judged(ranked_judged, k=10) == pytest.approx(0.6280, abs=1e-3)


def test_ndcg_from_judged_k50_hand_computed():
    ranked_judged = [(1, 2.0), (5, 1.0), (3, 0.0), (20, 2.0)]
    assert ndcg_from_judged(ranked_judged, k=50) == pytest.approx(0.7547, abs=1e-3)


def test_ndcg_from_judged_empty_returns_none():
    assert ndcg_from_judged([], k=10) is None


def test_ndcg_from_judged_no_positive_relevance_returns_none():
    # every judged item has relevance 0 -> IDCG == 0 -> undefined, not zero.
    assert ndcg_from_judged([(1, 0.0), (2, 0.0)], k=10) is None


# ---------------------------------------------------------------------------
# mean_reciprocal_rank
# ---------------------------------------------------------------------------


def test_mean_reciprocal_rank_excludes_none():
    # None entries are excluded from the mean, not zero-filled.
    assert mean_reciprocal_rank([1, None, 4]) == pytest.approx((1.0 + 0.25) / 2, abs=1e-9)


def test_mean_reciprocal_rank_all_none_is_nan():
    assert math.isnan(mean_reciprocal_rank([None, None]))


def test_mean_reciprocal_rank_empty_is_nan():
    assert math.isnan(mean_reciprocal_rank([]))


# ---------------------------------------------------------------------------
# expected_calibration_error
# ---------------------------------------------------------------------------


def test_ece_hand_computed():
    result = expected_calibration_error(
        [0.9, 0.9, 0.1, 0.1], [True, True, False, False], n_bins=10
    )
    assert result["ece"] == pytest.approx(0.10, abs=1e-6)
    assert result["n_bins_used"] == 2
    bins_by_lo = {b["bin_lo"]: b for b in result["bins"]}
    assert bins_by_lo[0.9]["mean_confidence"] == pytest.approx(0.9)
    assert bins_by_lo[0.9]["mean_outcome"] == pytest.approx(1.0)
    assert bins_by_lo[0.1]["mean_confidence"] == pytest.approx(0.1)
    assert bins_by_lo[0.1]["mean_outcome"] == pytest.approx(0.0)
    # bins sorted by bin_lo
    assert [b["bin_lo"] for b in result["bins"]] == sorted(b["bin_lo"] for b in result["bins"])


def test_ece_empty_confidences_returns_none_gracefully():
    result = expected_calibration_error([], [], n_bins=10)
    assert result == {"ece": None, "n_bins_used": 0, "bins": []}


def test_ece_confidence_exactly_one_lands_in_last_bin():
    # confidence == 1.0 must land in bin n_bins-1, not an out-of-range bin.
    result = expected_calibration_error([1.0], [True], n_bins=10)
    assert result["n_bins_used"] == 1
    assert result["bins"][0]["bin_lo"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# top_weighted_correlation — directional sanity checks (weighted-Pearson
# arithmetic is tedious to hand-verify exactly, per task instructions).
# ---------------------------------------------------------------------------


def test_top_weighted_correlation_perfect_alignment_near_plus_one():
    # near(1) maps to rank 1, mid(2) to rank 2, far(3) to rank 3 -- perfectly
    # aligned expected-vs-actual ordering, weighted toward the top (rank 1).
    expected_ordinal = [1.0, 2.0, 3.0]
    actual_rank = [1.0, 2.0, 3.0]
    corr = top_weighted_correlation(expected_ordinal, actual_rank)
    assert corr == pytest.approx(1.0, abs=1e-6)


def test_top_weighted_correlation_anti_aligned_near_minus_one():
    expected_ordinal = [1.0, 2.0, 3.0]
    actual_rank = [3.0, 2.0, 1.0]
    corr = top_weighted_correlation(expected_ordinal, actual_rank)
    assert corr == pytest.approx(-1.0, abs=1e-6)


def test_top_weighted_correlation_too_few_points_is_nan():
    assert math.isnan(top_weighted_correlation([1.0], [1.0]))


def test_top_weighted_correlation_zero_variance_is_nan():
    # actual_rank is constant -> wvar_y == 0 -> undefined.
    assert math.isnan(top_weighted_correlation([1.0, 2.0, 3.0], [5.0, 5.0, 5.0]))


# ---------------------------------------------------------------------------
# group_by_secret / compute_topheavy_metrics
# ---------------------------------------------------------------------------


def test_group_by_secret_excludes_unresolved():
    records = [
        {"secret": "s1", "actual_rank": 1},
        {"secret": "s1", "actual_rank": None},
        {"secret": "s2", "actual_rank": 3},
    ]
    groups = group_by_secret(records)
    assert set(groups) == {"s1", "s2"}
    assert len(groups["s1"]) == 1


def test_compute_topheavy_metrics_hand_computed_toy():
    result = compute_topheavy_metrics([_toy_group()])
    assert result["recall"][10]["mean"] == pytest.approx(2 / 3, abs=1e-3)
    assert result["precision"][10]["mean"] == pytest.approx(2 / 3, abs=1e-3)
    assert result["recall"][50]["mean"] == pytest.approx(1.0, abs=1e-3)
    assert result["precision"][50]["mean"] == pytest.approx(0.75, abs=1e-3)
    assert result["mrr"]["mean"] == pytest.approx(1.0, abs=1e-3)
    assert result["ndcg"][10]["mean"] == pytest.approx(0.6280, abs=1e-3)
    assert result["ndcg"][50]["mean"] == pytest.approx(0.7547, abs=1e-3)
    assert result["n_secrets"] == 1
    # |R| (near+mid tier count) for sec1 = {A, B, D} = 3.
    assert result["n_relevant"] == {"mean": 3.0, "min": 3, "max": 3, "values": [3], "n": 1}


def test_compute_topheavy_metrics_from_records_matches_manual_grouping():
    records = _toy_group()
    via_wrapper = compute_topheavy_metrics_from_records(records)
    via_manual = compute_topheavy_metrics([records])
    assert via_wrapper == via_manual


def test_compute_topheavy_metrics_empty_groups_no_exceptions():
    result = compute_topheavy_metrics([])
    assert result["n_secrets"] == 0
    for k in (10, 50, 100):
        assert result["ndcg"][k] == {"mean": None, "n": 0}
        assert result["recall"][k] == {"mean": None, "n": 0}
        assert result["precision"][k] == {"mean": None, "n": 0}
    assert result["mrr"] == {"mean": None, "n": 0}
    assert result["n_relevant"] == {"mean": None, "min": None, "max": None, "values": [], "n": 0}


def test_group_with_zero_relevant_tier_excluded_from_recall_mean():
    # A group entirely "far" tier has no relevant-tier records -> recall@k
    # is None for that group and must be EXCLUDED from the macro mean, not
    # counted as a zero.
    far_only = [{"secret": "s1", "tier": "far", "actual_rank": 1}]
    relevant_group = [
        {"secret": "s2", "tier": "near", "actual_rank": 1},
        {"secret": "s2", "tier": "mid", "actual_rank": 2},
    ]
    result = compute_topheavy_metrics([far_only, relevant_group])
    # only relevant_group contributes to recall@10 -> recall == 1.0 (both hit), n == 1
    assert result["recall"][10]["mean"] == pytest.approx(1.0, abs=1e-3)
    assert result["recall"][10]["n"] == 1


def test_group_with_zero_near_tier_excluded_from_mrr_mean():
    no_near = [{"secret": "s1", "tier": "mid", "actual_rank": 2}]
    has_near = [{"secret": "s2", "tier": "near", "actual_rank": 4}]
    result = compute_topheavy_metrics([no_near, has_near])
    assert result["mrr"]["n"] == 1
    assert result["mrr"]["mean"] == pytest.approx(0.25, abs=1e-6)


def test_same_secret_resampled_twice_counts_as_two_independent_groups():
    """The specific dedup bug the design warns against: a bootstrap draw
    that resamples the same secret twice must produce n=2 contributing
    entries for that secret's submetrics, NOT 1 (compute_topheavy_metrics
    must not re-group by secret name internally)."""
    group = _toy_group()  # secret "sec1"
    result = compute_topheavy_metrics([group, group])  # same secret, twice
    assert result["n_secrets"] == 2
    assert result["recall"][10]["n"] == 2
    assert result["precision"][10]["n"] == 2
    assert result["mrr"]["n"] == 2
    assert result["ndcg"][10]["n"] == 2
    # both draws are identical -> macro mean equals the single-draw value
    assert result["recall"][10]["mean"] == pytest.approx(2 / 3, abs=1e-3)


def test_topheavy_precision_saturation_now_explained_by_n_relevant():
    """Regression test for spec-metrics-ceiling-calibration.md WORKSTREAM 1
    action 1: before this change, n_relevant (|R|) was computed internally
    by compute_topheavy_metrics but never returned, so a caller seeing
    Precision@10=1.000 alongside a much lower Recall@10 had no way to check
    WHY without re-deriving |R| by hand from the raw records. This asserts
    n_relevant is now visible in the SAME returned dict, making the
    saturation mathematically checkable rather than silently hidden."""
    group = [
        {"secret": "s1", "tier": "near", "actual_rank": 5},  # only this one cracks top-10
        {"secret": "s1", "tier": "near", "actual_rank": 50},
        {"secret": "s1", "tier": "near", "actual_rank": 80},
    ]
    result = compute_topheavy_metrics([group])
    assert result["precision"][10]["mean"] == pytest.approx(1.0)
    assert result["recall"][10]["mean"] == pytest.approx(1 / 3, abs=1e-6)
    # Before this change n_relevant was invisible; now a caller can
    # reconstruct hit = recall * n_relevant = 1, explaining precision's
    # apparent perfection as "the one judged item that DID crack top-10
    # happened to be relevant", not "the model retrieved everything
    # relevant" -- the ceiling artifact is now legible from the dict alone.
    assert result["n_relevant"] == {"mean": 3.0, "min": 3, "max": 3, "values": [3], "n": 1}


# ---------------------------------------------------------------------------
# compute_nonsaturating_metrics / compute_nonsaturating_metrics_from_records
# ---------------------------------------------------------------------------
#
# Hand-computed on the same "sec1" toy fixture (see module docstring):
#   relevant (near/mid) records sorted by actual_rank: A(rank=1), B(rank=5),
#   D(rank=20) -> |R| = 3.
#   R-precision (== recall@|R|=3): hit = count with actual_rank<=3 = {A} = 1
#     -> r_precision = 1/3 = 0.33333.
#   MAP: AP = (1/1 [A is the 1st relevant found, at its own rank 1]
#             + 2/5 [B is the 2nd relevant found, at its own rank 5]
#             + 3/20 [D is the 3rd relevant found, at its own rank 20]) / 3
#          = (1 + 0.4 + 0.15) / 3 = 1.55 / 3 = 0.516667.
#   recall_at_fixed_k_near_r: k=3 -> hit=1 -> 1/3; k=4 -> hit=1 (still just
#     A) -> 1/3; k=5 -> hit=2 (A, B) -> 2/3; k=6 -> hit=2 (still A, B) -> 2/3.


def test_compute_nonsaturating_metrics_hand_computed_toy():
    result = compute_nonsaturating_metrics([_toy_group()])
    assert result["n_secrets"] == 1
    assert result["n_relevant"] == {"mean": 3.0, "min": 3, "max": 3, "values": [3], "n": 1}
    assert result["r_precision"]["mean"] == pytest.approx(1 / 3, abs=1e-6)
    assert result["r_precision"]["n"] == 1
    assert result["map"]["mean"] == pytest.approx(1.55 / 3, abs=1e-6)
    assert result["map"]["n"] == 1
    rk = result["recall_at_fixed_k_near_r"]
    assert rk[3]["mean"] == pytest.approx(1 / 3, abs=1e-6)
    assert rk[4]["mean"] == pytest.approx(1 / 3, abs=1e-6)
    assert rk[5]["mean"] == pytest.approx(2 / 3, abs=1e-6)
    assert rk[6]["mean"] == pytest.approx(2 / 3, abs=1e-6)


def test_compute_nonsaturating_metrics_from_records_matches_manual_grouping():
    records = _toy_group()
    via_wrapper = compute_nonsaturating_metrics_from_records(records)
    via_manual = compute_nonsaturating_metrics([records])
    assert via_wrapper == via_manual


def test_compute_nonsaturating_metrics_empty_groups_no_exceptions():
    result = compute_nonsaturating_metrics([])
    assert result["n_secrets"] == 0
    assert result["n_relevant"] == {"mean": None, "min": None, "max": None, "values": [], "n": 0}
    assert result["r_precision"] == {"mean": None, "n": 0}
    assert result["map"] == {"mean": None, "n": 0}
    for k in (3, 4, 5, 6):
        assert result["recall_at_fixed_k_near_r"][k] == {"mean": None, "n": 0}


def test_compute_nonsaturating_metrics_zero_relevant_group_excluded():
    # A group entirely "far" tier has |R|=0 -> r_precision/map/recall_at_fixed_k_near_r
    # must be None-excluded (not zero-filled) for that group, same convention as
    # compute_topheavy_metrics' recall@k.
    far_only = [{"secret": "s1", "tier": "far", "actual_rank": 1}]
    relevant_group = [
        {"secret": "s2", "tier": "near", "actual_rank": 1},
        {"secret": "s2", "tier": "mid", "actual_rank": 2},
    ]
    result = compute_nonsaturating_metrics([far_only, relevant_group])
    assert result["n_secrets"] == 2
    # only relevant_group (|R|=2) contributes: hit@2 = both ranks (1,2) <= 2 -> r_prec=1.0
    assert result["r_precision"]["mean"] == pytest.approx(1.0)
    assert result["r_precision"]["n"] == 1
    assert result["map"]["n"] == 1
    # n_relevant distribution still counts BOTH groups (0 and 2), unlike r_precision/map.
    assert result["n_relevant"]["values"] == [0, 2]
    assert result["n_relevant"]["n"] == 2


def test_same_secret_resampled_twice_counts_as_two_independent_groups_nonsaturating():
    """Mirrors the topheavy dedup-bootstrap regression test: a bootstrap
    draw resampling the same secret twice must contribute two independent
    entries, not be silently collapsed by internal re-grouping."""
    group = _toy_group()
    result = compute_nonsaturating_metrics([group, group])
    assert result["n_secrets"] == 2
    assert result["r_precision"]["n"] == 2
    assert result["map"]["n"] == 2
    assert result["r_precision"]["mean"] == pytest.approx(1 / 3, abs=1e-6)


# ---------------------------------------------------------------------------
# band_confusion_matrix / per_band_precision_recall
# ---------------------------------------------------------------------------


def _band_synthetic_records() -> list[dict]:
    # Hand-tallied expected counts (comment below), 4 records:
    #   R1: tier=near, actual_band=0 (win), expected_bands=[0,1] -> in_expected_band=True
    #   R2: tier=near, actual_band=2 (hot), expected_bands=[0,1] -> in_expected_band=False
    #   R3: tier=mid,  actual_band=1 (scorching), expected_bands=[1,2] -> in_expected_band=True
    #   R4: tier=far,  actual_band=1 (scorching), expected_bands=[4,5] -> in_expected_band=False
    #
    # Confusion matrix (rows near/mid/far, cols win/scorching/hot/warm/cold/freezing):
    #   near: [1, 0, 1, 0, 0, 0]   (R1 -> win, R2 -> hot)
    #   mid:  [0, 1, 0, 0, 0, 0]   (R3 -> scorching)
    #   far:  [0, 1, 0, 0, 0, 0]   (R4 -> scorching)
    return [
        {
            "secret": "s1",
            "tier": "near",
            "actual_rank": 1,
            "actual_band": 0,
            "expected_bands": [0, 1],
            "in_expected_band": True,
        },
        {
            "secret": "s1",
            "tier": "near",
            "actual_rank": 400,
            "actual_band": 2,
            "expected_bands": [0, 1],
            "in_expected_band": False,
        },
        {
            "secret": "s1",
            "tier": "mid",
            "actual_rank": 30,
            "actual_band": 1,
            "expected_bands": [1, 2],
            "in_expected_band": True,
        },
        {
            "secret": "s1",
            "tier": "far",
            "actual_rank": 25,
            "actual_band": 1,
            "expected_bands": [4, 5],
            "in_expected_band": False,
        },
    ]


def test_band_confusion_matrix_hand_tallied():
    records = _band_synthetic_records()
    result = band_confusion_matrix(records)
    assert result["tiers"] == ["near", "mid", "far"]
    assert result["bands"] == ["win", "scorching", "hot", "warm", "cold", "freezing"]
    assert result["matrix"] == [
        [1, 0, 1, 0, 0, 0],
        [0, 1, 0, 0, 0, 0],
        [0, 1, 0, 0, 0, 0],
    ]


def test_band_confusion_matrix_excludes_unresolved():
    records = _band_synthetic_records()
    records.append({"secret": "s1", "tier": "near", "actual_rank": None, "actual_band": None})
    result = band_confusion_matrix(records)
    assert sum(sum(row) for row in result["matrix"]) == 4  # unresolved record not tallied


def test_per_band_precision_recall_hand_tallied():
    # Hand tally (expected_bands: R1=[0,1], R2=[0,1], R3=[1,2], R4=[4,5];
    # in_expected_band: R1=True, R2=False, R3=True, R4=False):
    #   band "win" (0): predicted={R1} (actual_band==0).
    #     expected = records with 0 in expected_bands = {R1,R2} -> n_expected=2.
    #     precision = mean(in_expected_band for {R1}) = 1.0
    #     recall = sum(in_expected_band for predicted)/n_expected = 1/2 = 0.5
    #   band "scorching" (1): predicted={R3,R4} (actual_band==1).
    #     expected = records with 1 in expected_bands = {R1,R2,R3} -> n_expected=3.
    #     precision = mean(True(R3), False(R4)) = 0.5
    #     recall = sum(in_expected_band for predicted)/n_expected = 1(R3)/3 = 0.3333
    #   band "hot" (2): predicted={R2}. expected = records with 2 in expected_bands
    #     = {R3} -> n_expected=1. precision = mean(False) = 0.0; recall = 0/1 = 0.0
    #   band "warm" (3): predicted={}, expected={} -> both None
    #   band "cold" (4): predicted={}, expected={R4} -> precision=None (empty
    #     predicted), recall = 0/1 = 0.0
    #   band "freezing" (5): predicted={}, expected={R4} -> precision=None,
    #     recall = 0/1 = 0.0
    records = _band_synthetic_records()
    result = per_band_precision_recall(records)
    assert result["win"]["precision"] == pytest.approx(1.0)
    assert result["win"]["recall"] == pytest.approx(0.5)
    assert result["win"]["n_predicted"] == 1
    assert result["win"]["n_expected"] == 2
    assert result["scorching"]["precision"] == pytest.approx(0.5)
    assert result["scorching"]["recall"] == pytest.approx(1 / 3, abs=1e-6)
    assert result["scorching"]["n_predicted"] == 2
    assert result["scorching"]["n_expected"] == 3
    assert result["hot"]["precision"] == pytest.approx(0.0)
    assert result["hot"]["recall"] == pytest.approx(0.0)
    assert result["hot"]["n_predicted"] == 1
    assert result["hot"]["n_expected"] == 1
    assert result["warm"]["precision"] is None
    assert result["warm"]["recall"] is None
    assert result["warm"]["n_predicted"] == 0
    assert result["warm"]["n_expected"] == 0
    assert result["cold"]["precision"] is None
    assert result["cold"]["recall"] == pytest.approx(0.0)
    assert result["cold"]["n_predicted"] == 0
    assert result["cold"]["n_expected"] == 1
    assert result["freezing"]["precision"] is None
    assert result["freezing"]["recall"] == pytest.approx(0.0)
    assert result["freezing"]["n_predicted"] == 0
    assert result["freezing"]["n_expected"] == 1


def test_per_band_precision_recall_empty_records_no_exceptions():
    result = per_band_precision_recall([])
    for band in result.values():
        assert band == {"precision": None, "recall": None, "n_predicted": 0, "n_expected": 0}


# ---------------------------------------------------------------------------
# band_calibration_error
# ---------------------------------------------------------------------------


def test_band_calibration_error_delegates_to_ece():
    # vocab_size=10 -> rank 1 => confidence 0.9, rank 9 => confidence 0.1
    records = [
        {"tier": "near", "actual_rank": 1},
        {"tier": "near", "actual_rank": 1},
        {"tier": "far", "actual_rank": 9},
        {"tier": "far", "actual_rank": 9},
    ]
    result = band_calibration_error(records, vocab_size=10, n_bins=10)
    assert result["ece"] == pytest.approx(0.10, abs=1e-6)


def test_band_calibration_error_empty_records_no_exceptions():
    result = band_calibration_error([], vocab_size=100)
    assert result == {"ece": None, "n_bins_used": 0, "bins": []}


def test_band_calibration_error_excludes_unresolved():
    records = [
        {"tier": "near", "actual_rank": None},
        {"tier": "near", "actual_rank": 1},
    ]
    result = band_calibration_error(records, vocab_size=10)
    assert result["n_bins_used"] == 1  # only the one resolved record contributes
