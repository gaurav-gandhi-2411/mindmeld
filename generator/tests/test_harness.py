from __future__ import annotations

"""
Eval-harness CI gates — dimensions 1, 2, 4, 5 (algorithmic, fast, always run).

Dimension 3 (local LLM judge) is NOT gated here: it needs Ollama running
locally, which CI/most dev machines won't have — see
tests/test_harness_judge.py, which self-skips with a clear message when the
judge is unreachable rather than failing the whole suite.

Thresholds are set as REGRESSION FLOORS just under the measured baseline
(see evals/reports/baseline_report.md), not aspirational targets — several
of these numbers document known, real product limitations (see PLAN.md's
"MAJOR FINDING" entry on hi-en cross-lingual ranking). The point of these
gates is "don't silently get worse than what's already shipped and
documented", not "pretend the baseline is good."
"""

import pytest

from evals.harness.dimension1_ranking import run_dimension1
from evals.harness.dimension2_crosslang import run_dimension2
from evals.harness.dimension4_rival import run_dimension4
from evals.harness.dimension5_winrate import run_dimension5

# ---------------------------------------------------------------------------
# Dimension 1 — semantic ranking quality
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dim1_en():
    return run_dimension1("en")


@pytest.fixture(scope="module")
def dim1_hien():
    return run_dimension1("hi-en")


def test_dim1_en_near_band_accuracy_floor(dim1_en):
    # Baseline measured 0.96 — floor set with a small buffer for embedding-
    # cache/model version drift, not to tolerate a real regression.
    assert dim1_en["band_accuracy"]["near"] >= 0.85


def test_dim1_en_spearman_floor(dim1_en):
    # Baseline measured 0.837.
    assert dim1_en["spearman_correlation"] >= 0.70


def test_dim1_en_monotonicity_ceiling(dim1_en):
    # Baseline measured 6.2% violation rate.
    assert dim1_en["monotonicity"]["violation_rate"] <= 0.15


def test_dim1_hien_pipeline_runs(dim1_hien):
    # KNOWN BASELINE ISSUE (see PLAN.md): hi-en near-tier band-accuracy is
    # currently ~8% (translation subtype ~0%, associate ~13%) — the
    # multilingual model's romanized-Hindi query embeddings are poorly
    # grounded (see dimension2's much larger 60-pair confirmation). This gate
    # only proves the pipeline runs and produces a real (non-crashed, non-
    # empty) result — NOT that the numbers are good. Tightening this gate is
    # a product decision (swap model / redesign hi-en ranking), tracked
    # separately, not silently done by loosening a test.
    assert dim1_hien["n_scenarios"] > 0
    assert dim1_hien["band_accuracy"]["overall"] is not None


def test_dim1_hien_far_tier_still_works(dim1_hien):
    # The far-tier (seeded-random, safe-to-automate) accuracy is NOT
    # affected by the translation-grounding issue — regression here would
    # indicate something more broadly broken, not the known limitation.
    assert dim1_hien["band_accuracy"]["far"] >= 0.85


# ---------------------------------------------------------------------------
# Dimension 2 — cross-language consistency
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dim2():
    return run_dimension2()


def test_dim2_pipeline_runs(dim2):
    assert dim2["n_resolved"] >= 55  # 60 pairs, at most a handful of vocab-coverage gaps


def test_dim2_known_baseline_not_worse(dim2):
    # KNOWN BASELINE ISSUE: pass rate ~5%, median rank ~47th percentile (see
    # PLAN.md). Floor set at a small buffer below measured to catch further
    # regression without pretending this number is acceptable.
    assert dim2["pass_rate_scorching_or_hot"] >= 0.02
    assert dim2["median_rank_percentile"] <= 60.0


# ---------------------------------------------------------------------------
# Dimension 4 — rival calibration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dim4():
    return run_dimension4()


def test_dim4_par_within_target(dim4):
    # Baseline measured 100% within [4,16], median par 8.0.
    assert dim4["par_within_target_range"] >= 0.95
    assert dim4["median_within_target"] is True


def test_dim4_spreads_within_target(dim4):
    assert dim4["chill_spread_within_target"] >= 0.90
    assert dim4["sharp_spread_within_target"] >= 0.90


def test_dim4_no_flagged_puzzles_regression(dim4):
    # Baseline measured 0 flagged puzzles out of 220.
    assert dim4["n_flagged"] <= 5


# ---------------------------------------------------------------------------
# Dimension 5 — difficulty / win-rate modeling
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dim5():
    return run_dimension5()


def test_dim5_pipeline_runs(dim5):
    assert dim5["n_puzzles"] > 0
    assert 0.0 <= dim5["median_win_rate"] <= 1.0


def test_dim5_no_unwinnable_puzzles(dim5):
    # Baseline measured 0 outliers below 40% win-rate — a puzzle simulated
    # players essentially never win would be a real content problem.
    assert dim5["n_outliers_too_hard"] == 0


# ---------------------------------------------------------------------------
# Regression proof — a deliberately-broken clue/rank MUST fail the harness.
# (spec acceptance criterion 4: "prove it with a test", not just assert it)
# ---------------------------------------------------------------------------


def test_broken_clue_is_caught_by_spoiler_gate():
    """A clue that literally states its own secret must be flagged as a
    leak by the same clue_leak_reason() predicate the real spoiler gate
    (tests/test_clue_spoiler_gate.py) runs on every real clue — proving the
    gate has teeth, not just that real (already-clean) clues happen to pass."""
    from build_packs import clue_leak_reason

    secret = "ocean"
    broken_clue = "Vast and salty, this ocean covers most of the planet."
    leak = clue_leak_reason(broken_clue, secret, aliases=[])
    assert leak is not None, (
        "REGRESSION: a clue containing its own secret verbatim was NOT "
        "flagged as a spoiler leak — the spoiler gate has lost its teeth."
    )


def test_broken_rank_scenario_is_caught_by_dimension1():
    """A synthetic scenario that mislabels a definitely-unrelated word as
    'near' (expecting Scorching/Hot) must be flagged as NOT in its expected
    band by dimension1's own scoring — proving band-accuracy is a real
    check that can fail, not a metric that always reports 100% regardless
    of input."""
    from evals.harness.dimension1_ranking import _resolve_actuals

    # "ocean" vs "bureaucracy" have no meaningful semantic relationship —
    # mislabeling this pair as "near" (expecting rank inside the top ~0.1%
    # of a 55k-word vocab) should be caught, not silently pass.
    broken_scenario = [
        {
            "secret": "ocean",
            "word": "bureaucracy",
            "tier": "near",
            "expected_bands": [1, 2],
            "subtype": None,
            "note": None,
        }
    ]
    resolved = _resolve_actuals(broken_scenario, "en")
    assert len(resolved) == 1
    rec = resolved[0]
    assert rec["resolution_error"] is None, "both words must be in-vocab for this proof to be valid"
    assert rec["in_expected_band"] is False, (
        "REGRESSION: dimension 1's band-accuracy check did not catch an "
        "obviously-mislabeled (unrelated word, 'near' tier) scenario — the "
        "gate has lost its teeth."
    )
