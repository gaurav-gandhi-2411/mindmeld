from __future__ import annotations

"""
Unit tests for spec-model-excellence.md WORKSTREAM D item 13's prep +
scoring modules: evals/finetune/prepare_label_ceiling_sample.py (stratified
sampling logic) and evals/finetune/score_label_ceiling.py (agreement/kappa
computation). Model-free, runs in milliseconds -- no CSV/model I/O beyond
tmp_path fixtures.

The kappa golden values in test_cohens_kappa_matches_hand_derived_* are
derived independently by hand from the standard Cohen's-kappa formula
(po/pe from marginal proportions), NOT by running this module's own
implementation and asserting self-consistency -- see each test's docstring
for the confusion matrix and the by-hand arithmetic.
"""

import csv

import numpy as np
import pytest

from evals.finetune.prepare_label_ceiling_sample import (
    CSV_COLUMNS,
    PER_TIER_TARGET,
    TIERS,
    _allocate_per_domain,
    build_stratification_breakdown,
    stratified_sample,
    write_csv,
)
from evals.finetune.score_label_ceiling import (
    CATEGORIES,
    bootstrap_kappa_ci,
    cohens_kappa,
    confusion_matrix,
    join_with_ai_tier,
    raw_agreement_rate,
    score,
)

# ---------------------------------------------------------------------------
# prepare_label_ceiling_sample._allocate_per_domain
# ---------------------------------------------------------------------------


def test_allocate_per_domain_proportional_even_population():
    pop = {"a": 10, "b": 10, "c": 10}
    alloc = _allocate_per_domain(pop, 9)
    assert alloc == {"a": 3, "b": 3, "c": 3}
    assert sum(alloc.values()) == 9


def test_allocate_per_domain_respects_rounding_remainder():
    # 10 target across a:5,b:5 population -> exact split, no remainder.
    # 7 target across a:5,b:5 -> 3.5/3.5 floors to 3/3, remainder 1 goes to
    # whichever domain wins the (deterministic, alphabetical-tiebreak) tie.
    alloc = _allocate_per_domain({"a": 5, "b": 5}, 7)
    assert sum(alloc.values()) == 7
    assert alloc["a"] in (3, 4) and alloc["b"] in (3, 4)


def test_allocate_per_domain_never_exceeds_population_cap():
    pop = {"a": 2, "b": 100}
    alloc = _allocate_per_domain(pop, 20)
    assert alloc["a"] <= 2
    assert sum(alloc.values()) == 20


def test_allocate_per_domain_target_exceeds_total_population_caps_at_total():
    pop = {"a": 2, "b": 3}
    alloc = _allocate_per_domain(pop, 100)
    assert sum(alloc.values()) == 5
    assert alloc == {"a": 2, "b": 3}


def test_allocate_per_domain_zero_target_or_population():
    assert _allocate_per_domain({"a": 5}, 0) == {"a": 0}
    assert _allocate_per_domain({"a": 0, "b": 0}, 5) == {"a": 0, "b": 0}


# ---------------------------------------------------------------------------
# prepare_label_ceiling_sample.stratified_sample
# ---------------------------------------------------------------------------


def _synthetic_records() -> list[dict]:
    """2 domains x 3 tiers, 6 records/cell -- enough to exercise per-tier,
    per-domain allocation without touching real benchmark data."""
    records = []
    for secret_prefix, domain in (("dsecretA", "dom1"), ("dsecretB", "dom2")):
        for tier in TIERS:
            for i in range(6):
                records.append(
                    {
                        "secret": f"{secret_prefix}",
                        "word": f"{tier}_{domain}_{i}",
                        "tier": tier,
                        "domain": domain,
                    }
                )
    return records


def _domain_of_synthetic() -> dict[str, str]:
    return {"dsecretA": "dom1", "dsecretB": "dom2"}


def test_stratified_sample_hits_per_tier_target_when_population_allows():
    records = _synthetic_records()
    domain_of = _domain_of_synthetic()
    sample = stratified_sample(records, domain_of, per_tier_target=4, seed=42)
    counts = {t: sum(1 for r in sample if r["tier"] == t) for t in TIERS}
    assert counts == {t: 4 for t in TIERS}
    assert len(sample) == 12


def test_stratified_sample_spans_multiple_domains_per_tier():
    records = _synthetic_records()
    domain_of = _domain_of_synthetic()
    sample = stratified_sample(records, domain_of, per_tier_target=4, seed=42)
    domains_seen = {domain_of[r["secret"]] for r in sample}
    assert domains_seen == {"dom1", "dom2"}


def test_stratified_sample_no_duplicate_rows():
    records = _synthetic_records()
    domain_of = _domain_of_synthetic()
    sample = stratified_sample(records, domain_of, per_tier_target=6, seed=42)
    keys = [(r["secret"], r["word"]) for r in sample]
    assert len(keys) == len(set(keys))


def test_stratified_sample_reproducible_given_same_seed():
    records = _synthetic_records()
    domain_of = _domain_of_synthetic()
    a = stratified_sample(records, domain_of, per_tier_target=4, seed=42)
    b = stratified_sample(records, domain_of, per_tier_target=4, seed=42)
    assert [(r["secret"], r["word"]) for r in a] == [(r["secret"], r["word"]) for r in b]


def test_stratified_sample_is_shuffled_not_tier_grouped():
    """Blind annotation requires row ORDER to carry no tier signal -- an
    unshuffled tier-by-tier sample would put all "near" rows first, all
    "far" rows last, silently leaking the withheld label via position."""
    records = _synthetic_records()
    domain_of = _domain_of_synthetic()
    sample = stratified_sample(records, domain_of, per_tier_target=6, seed=42)
    tiers_in_order = [r["tier"] for r in sample]
    # An unshuffled tier-grouped list has exactly 2 "boundaries" (near->mid,
    # mid->far); a shuffled list should have many more adjacent-tier changes.
    pairs = zip(tiers_in_order, tiers_in_order[1:], strict=False)
    boundaries = sum(1 for a, b in pairs if a != b)
    assert boundaries > 2


def test_stratified_sample_caps_at_available_population():
    records = _synthetic_records()
    domain_of = _domain_of_synthetic()
    # only 6 records/(tier,domain) cell x 2 domains = 12 max per tier
    sample = stratified_sample(records, domain_of, per_tier_target=100, seed=42)
    counts = {t: sum(1 for r in sample if r["tier"] == t) for t in TIERS}
    assert counts == {t: 12 for t in TIERS}


def test_build_stratification_breakdown_matches_sample_counts():
    records = _synthetic_records()
    domain_of = _domain_of_synthetic()
    sample = stratified_sample(records, domain_of, per_tier_target=4, seed=42)
    breakdown = build_stratification_breakdown(sample)
    assert sum(sum(d.values()) for d in breakdown.values()) == len(sample)
    for tier in TIERS:
        assert sum(breakdown[tier].values()) == sum(1 for r in sample if r["tier"] == tier)


def test_real_default_per_tier_target_is_25():
    # Documents the module's actual size choice (75 total / 3 tiers).
    assert PER_TIER_TARGET == 25


def test_write_csv_has_exact_expected_columns_and_blank_judgment(tmp_path):
    records = [
        {"secret": "s1", "word": "w1", "domain": "dom1", "tier": "near"},
        {"secret": "s1", "word": "w2", "domain": "dom1", "tier": "far"},
    ]
    out_path = tmp_path / "sample.csv"
    write_csv(records, out_path)
    with out_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0].keys() == set(CSV_COLUMNS)
    assert all(r["gg_tier_judgment"] == "" for r in rows)
    assert {r["word"] for r in rows} == {"w1", "w2"}


# ---------------------------------------------------------------------------
# score_label_ceiling.confusion_matrix / cohens_kappa -- hand-derived golden
# values (see module docstring).
# ---------------------------------------------------------------------------


def test_cohens_kappa_matches_hand_derived_2x2_unweighted_example():
    """Classic textbook 2x2 example, categories ("yes","no"):
        rows=A, cols=B:  A=yes/B=yes=20, A=yes/B=no=5, A=no/B=yes=10, A=no/B=no=15
    n=50, po=(20+15)/50=0.70, marginals A=(25,25)/50, B=(30,20)/50,
    pe=0.5*0.6 + 0.5*0.4 = 0.5, kappa=(0.70-0.50)/(1-0.50)=0.40 exactly.
    With only 2 categories, linear and unweighted kappa coincide (there is
    only one off-diagonal "distance"), so this also exercises the linear path.
    """
    pairs = [("yes", "yes")] * 20 + [("yes", "no")] * 5 + [("no", "yes")] * 10 + [("no", "no")] * 15
    kappa_unweighted = cohens_kappa(pairs, categories=("yes", "no"), weights="none")
    kappa_linear = cohens_kappa(pairs, categories=("yes", "no"), weights="linear")
    assert kappa_unweighted == pytest.approx(0.4, abs=1e-9)
    assert kappa_linear == pytest.approx(0.4, abs=1e-9)


def test_cohens_kappa_matches_hand_derived_3x3_linear_weighted_example():
    """3x3 ordinal confusion matrix (categories near=0,mid=1,far=2), rows=AI,
    cols=GG:
        near/near=6, near/mid=2, near/far=0
        mid/near=1,  mid/mid=10, mid/far=1
        far/near=0,  far/mid=2,  far/far=8
    n=30. By-hand linear-weighted-kappa arithmetic (weights w_ij=1-|i-j|/2):
    po=0.9, pe=0.595555..., kappa=(0.9-0.595555...)/(1-0.595555...)
    = 0.7527472527472525 (computed independently via numpy scratch, see PR
    description / task notes -- not by calling this module's own function).
    """
    m = {
        ("near", "near"): 6,
        ("near", "mid"): 2,
        ("near", "far"): 0,
        ("mid", "near"): 1,
        ("mid", "mid"): 10,
        ("mid", "far"): 1,
        ("far", "near"): 0,
        ("far", "mid"): 2,
        ("far", "far"): 8,
    }
    pairs = [pair for pair, count in m.items() for _ in range(count)]
    kappa = cohens_kappa(pairs, categories=CATEGORIES, weights="linear")
    assert kappa == pytest.approx(0.7527472527472525, abs=1e-9)


def test_confusion_matrix_shape_and_counts():
    pairs = [("near", "near"), ("near", "far"), ("far", "far")]
    m = confusion_matrix(pairs)
    assert m.shape == (3, 3)
    assert m.sum() == 3
    assert m[CATEGORIES.index("near"), CATEGORIES.index("near")] == 1
    assert m[CATEGORIES.index("near"), CATEGORIES.index("far")] == 1
    assert m[CATEGORIES.index("far"), CATEGORIES.index("far")] == 1


def test_raw_agreement_rate_basic():
    pairs = [("near", "near"), ("near", "far"), ("mid", "mid"), ("far", "near")]
    assert raw_agreement_rate(pairs) == pytest.approx(0.5)


def test_raw_agreement_rate_empty_is_none():
    assert raw_agreement_rate([]) is None


def test_bootstrap_kappa_ci_point_matches_plain_kappa_and_ci_brackets_it():
    pairs = [("near", "near")] * 10 + [("near", "mid")] * 3 + [("far", "far")] * 10
    result = bootstrap_kappa_ci(pairs, weights="linear", n_boot=500, seed=42)
    plain = cohens_kappa(pairs, weights="linear")
    assert result["point"] == pytest.approx(plain)
    assert result["ci_95"] is not None
    lo, hi = result["ci_95"]
    assert lo <= result["point"] <= hi


def test_bootstrap_kappa_ci_empty_pairs_returns_none_ci():
    result = bootstrap_kappa_ci([], n_boot=100)
    assert result["ci_95"] is None
    assert result["n_pairs"] == 0


def test_perfect_agreement_gives_kappa_one():
    pairs = [("near", "near"), ("mid", "mid"), ("far", "far")] * 5
    assert cohens_kappa(pairs, weights="linear") == pytest.approx(1.0)
    assert cohens_kappa(pairs, weights="none") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# score_label_ceiling.join_with_ai_tier / score / score_csv (I/O via tmp_path)
# ---------------------------------------------------------------------------


def test_join_with_ai_tier_skips_blank_and_invalid_and_missing_pair():
    ai_lookup = {("s1", "w1"): "near", ("s1", "w2"): "far"}
    rows = [
        {"secret": "s1", "word": "w1", "domain": "d", "gg_tier_judgment": "near"},
        {"secret": "s1", "word": "w2", "domain": "d", "gg_tier_judgment": ""},
        {"secret": "s1", "word": "w3", "domain": "d", "gg_tier_judgment": "near"},
        {"secret": "s1", "word": "w1", "domain": "d", "gg_tier_judgment": "bogus"},
    ]
    joined = join_with_ai_tier(rows, ai_lookup)
    assert len(joined["scored"]) == 1
    assert joined["scored"][0] == {
        "secret": "s1",
        "word": "w1",
        "ai_tier": "near",
        "gg_tier": "near",
    }
    assert len(joined["skipped"]) == 3


def test_join_with_ai_tier_case_insensitive_and_whitespace_tolerant():
    ai_lookup = {("s1", "w1"): "near"}
    rows = [{"secret": "s1", "word": "w1", "domain": "d", "gg_tier_judgment": "  NEAR  "}]
    joined = join_with_ai_tier(rows, ai_lookup)
    assert len(joined["scored"]) == 1
    assert joined["scored"][0]["gg_tier"] == "near"


def test_score_reports_n_scored_and_confusion_matrix_shape():
    scored = [
        {"ai_tier": "near", "gg_tier": "near"},
        {"ai_tier": "far", "gg_tier": "mid"},
    ]
    result = score(scored)
    assert result["n_scored"] == 2
    assert (
        result["confusion_matrix"]["matrix"]
        == confusion_matrix([("near", "near"), ("far", "mid")]).tolist()
    )


def test_score_csv_end_to_end_with_synthetic_completed_csv(tmp_path, monkeypatch):
    """Mirrors the manual synthetic-CSV check this task's report describes:
    half the rows filled with the correct (withheld) AI tier, half with a
    deliberately wrong tier -- must yield 0.5 raw agreement, not crash, and
    correctly report the confusion matrix."""
    import evals.finetune.score_label_ceiling as mod

    staging = tmp_path / "dim1_hien.json"
    staging.write_text(
        '[{"secret":"s1","word":"w1","tier":"near"},'
        '{"secret":"s1","word":"w2","tier":"far"},'
        '{"secret":"s2","word":"w3","tier":"mid"},'
        '{"secret":"s2","word":"w4","tier":"near"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "STAGING_DIM1_HIEN", staging)

    csv_path = tmp_path / "completed.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["secret", "word", "domain", "gg_tier_judgment"])
        writer.writeheader()
        # correct: matches withheld AI tier
        writer.writerow({"secret": "s1", "word": "w1", "domain": "d", "gg_tier_judgment": "near"})
        writer.writerow({"secret": "s2", "word": "w3", "domain": "d", "gg_tier_judgment": "mid"})
        # wrong: deliberately mismatched
        writer.writerow({"secret": "s1", "word": "w2", "domain": "d", "gg_tier_judgment": "near"})
        writer.writerow({"secret": "s2", "word": "w4", "domain": "d", "gg_tier_judgment": "far"})

    result = mod.score_csv(csv_path)
    assert result["n_scored"] == 4
    assert result["n_skipped"] == 0
    assert result["raw_agreement_rate"] == pytest.approx(0.5)
    assert result["weighted_kappa_linear"]["point"] is not None
    assert not np.isnan(result["weighted_kappa_linear"]["point"])
