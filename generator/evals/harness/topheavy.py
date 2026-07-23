from __future__ import annotations

"""
Top-heavy ranking metrics (NDCG@k, MRR, Recall@k, Precision@k) and band-
calibration metrics (band-confusion matrix, per-band precision/recall,
band-derived expected calibration error), computed from already-resolved
dimension-1 records — i.e. the output of
`evals.harness.dimension1_ranking._resolve_actuals` / the `dim1_records`
list persisted in a bake-off checkpoint (evals/finetune/data/bakeoff_raw/
*.json). Every function here is a pure aggregation over records that
already carry `actual_rank`/`actual_band`; no embedding or model call
happens in this module.

Source of the requirement: spec-model-excellence.md, WORKSTREAM A
("task-appropriate metric suite") — global Spearman spends most of its
mass on rank regions no user ever perceives and weights a tail error the
same as a top-of-list error; these metrics instead emphasise the top of
the ranking (NDCG/MRR/Recall/Precision@k) and the model's user-facing
temperature-band output (confusion matrix / per-band P-R / ECE).
"""

import numpy as np

from evals.harness.dimension1_ranking import _TIER_ORDINAL  # reuse, don't redefine
from evals.harness.metrics import (
    expected_calibration_error,
    mean_reciprocal_rank,
    ndcg_from_judged,
)

_RELEVANCE_GRADE = {"near": 2.0, "mid": 1.0, "far": 0.0}
# Binary-relevance set for Recall/Precision; "far" is the authored decoy/negative class.
_RELEVANT_TIERS = {"near", "mid"}
K_VALUES = (10, 50, 100)

# Sanity check: this module's relevance-grade tier taxonomy must never drift
# out of sync with dimension1_ranking's canonical tier-ordinal taxonomy —
# fail loudly at import time rather than silently scoring an unknown tier.
assert set(_RELEVANCE_GRADE) == set(_TIER_ORDINAL), (
    "topheavy._RELEVANCE_GRADE tiers diverged from dimension1_ranking._TIER_ORDINAL"
)

_TIERS = ("near", "mid", "far")
_BAND_NAMES = ("win", "scorching", "hot", "warm", "cold", "freezing")


def group_by_secret(records: list[dict]) -> dict[str, list[dict]]:
    """Group RESOLVED records (actual_rank is not None) by secret."""
    by_secret: dict[str, list[dict]] = {}
    for r in records:
        if r["actual_rank"] is None:
            continue
        by_secret.setdefault(r["secret"], []).append(r)
    return by_secret


def _agg(values: list[float]) -> dict:
    return {"mean": float(np.mean(values)) if values else None, "n": len(values)}


def compute_topheavy_metrics(secret_groups) -> dict:
    """secret_groups: an ITERABLE of per-secret judged-record lists.

    CRITICAL: this must NOT re-group by secret name internally. Callers
    doing cluster-bootstrap resampling (see bootstrap_ci.bootstrap_topheavy_ci)
    pass one list entry per RESAMPLED draw of a secret, and the same secret
    name can legitimately appear more than once across draws — each draw
    must count as its own independent macro-average contribution.
    Re-grouping by name here would silently collapse resampled duplicates
    back into one, corrupting the bootstrap. Accept the groups exactly as
    given.

    For each group (one secret's judged records), for each k in K_VALUES:
      - ndcg@k via ndcg_from_judged
      - recall@k = (# relevant-tier records with actual_rank<=k) / (# relevant-tier
        records in group), None if group has zero relevant-tier records
      - precision@k = (# relevant-tier records with actual_rank<=k) / (# ANY-tier
        records with actual_rank<=k), None if zero records in group have
        actual_rank<=k

    Also, per group: the rank of its best (min actual_rank) near-tier (NOT
    mid) record, or None if the group has no near-tier record — collected
    across groups and passed to mean_reciprocal_rank.

    Macro-averages every per-group value across groups where it is not
    None (each metric tracks n = count of contributing groups, since some
    metrics — especially precision@10 — will often have very few
    contributing groups given ~2-6 judged words per secret; n is reported
    honestly rather than hiding a sparse denominator).
    """
    ndcg_values: dict[int, list[float]] = {k: [] for k in K_VALUES}
    recall_values: dict[int, list[float]] = {k: [] for k in K_VALUES}
    precision_values: dict[int, list[float]] = {k: [] for k in K_VALUES}
    mrr_ranks: list[int | None] = []
    n_secrets = 0

    for group in secret_groups:
        n_secrets += 1
        ranked_judged = [(r["actual_rank"], _RELEVANCE_GRADE[r["tier"]]) for r in group]
        relevant_records = [r for r in group if r["tier"] in _RELEVANT_TIERS]
        n_relevant = len(relevant_records)

        near_records = [r for r in group if r["tier"] == "near"]
        best_near_rank = min((r["actual_rank"] for r in near_records), default=None)
        mrr_ranks.append(best_near_rank)

        for k in K_VALUES:
            ndcg = ndcg_from_judged(ranked_judged, k)
            if ndcg is not None:
                ndcg_values[k].append(ndcg)

            if n_relevant > 0:
                hit = sum(1 for r in relevant_records if r["actual_rank"] <= k)
                recall_values[k].append(hit / n_relevant)

            judged_at_k = [r for r in group if r["actual_rank"] <= k]
            if judged_at_k:
                relevant_at_k = sum(1 for r in judged_at_k if r["tier"] in _RELEVANT_TIERS)
                precision_values[k].append(relevant_at_k / len(judged_at_k))

    mrr_valid = [r for r in mrr_ranks if r is not None]
    mrr = {
        "mean": mean_reciprocal_rank(mrr_ranks) if mrr_valid else None,
        "n": len(mrr_valid),
    }

    return {
        "ndcg": {k: _agg(ndcg_values[k]) for k in K_VALUES},
        "recall": {k: _agg(recall_values[k]) for k in K_VALUES},
        "precision": {k: _agg(precision_values[k]) for k in K_VALUES},
        "mrr": mrr,
        "n_secrets": n_secrets,
    }


def compute_topheavy_metrics_from_records(records: list[dict]) -> dict:
    """Convenience wrapper for the non-bootstrap point estimate: group
    records by secret name (group_by_secret), then compute_topheavy_metrics
    on the resulting groups. Do NOT use this inside a bootstrap resample
    loop (see the warning on compute_topheavy_metrics) — only for the
    single point-estimate call.
    """
    by_secret = group_by_secret(records)
    return compute_topheavy_metrics(by_secret.values())


def band_confusion_matrix(records: list[dict]) -> dict:
    """rows = tier (near/mid/far), cols = band name (win/scorching/hot/warm/
    cold/freezing, ordinals 0-5). Cell = count of records with that tier
    whose actual_band == that column. Pure tally over RESOLVED records
    (actual_rank is not None) — no relevance-grade logic needed here.
    """
    matrix = [[0 for _ in _BAND_NAMES] for _ in _TIERS]
    tier_idx = {t: i for i, t in enumerate(_TIERS)}
    for r in records:
        if r["actual_rank"] is None:
            continue
        matrix[tier_idx[r["tier"]]][r["actual_band"]] += 1
    return {"tiers": list(_TIERS), "bands": list(_BAND_NAMES), "matrix": matrix}


def per_band_precision_recall(records: list[dict]) -> dict:
    """For each band b in 0..5:
      predicted_b = records with actual_band == b
      expected_b = records with b in record['expected_bands']
      precision(b) = mean(r['in_expected_band'] for r in predicted_b), None
        if predicted_b empty
      recall(b) = |predicted_b intersect expected_b| / |expected_b|, None if
        expected_b empty (intersect = records that are in BOTH predicted_b
        and expected_b — since predicted_b already filters actual_band==b, a
        record in predicted_b is in the intersection iff its
        in_expected_band is True AND b in its expected_bands, i.e. iff
        r['in_expected_band'] is True for that r — because in_expected_band
        is defined as actual_band in expected_bands, and actual_band==b
        here, so in_expected_band==True implies b in expected_bands.)
    """
    resolved = [r for r in records if r["actual_rank"] is not None]
    out: dict[str, dict] = {}
    for b, name in enumerate(_BAND_NAMES):
        predicted_b = [r for r in resolved if r["actual_band"] == b]
        expected_b = [r for r in resolved if b in r["expected_bands"]]
        precision = (
            sum(1 for r in predicted_b if r["in_expected_band"]) / len(predicted_b)
            if predicted_b
            else None
        )
        recall = (
            sum(1 for r in predicted_b if r["in_expected_band"]) / len(expected_b)
            if expected_b
            else None
        )
        out[name] = {
            "precision": precision,
            "recall": recall,
            "n_predicted": len(predicted_b),
            "n_expected": len(expected_b),
        }
    return out


def band_calibration_error(records: list[dict], vocab_size: int, n_bins: int = 10) -> dict:
    """Operationalizes 'band calibration' as: does the model's rank-derived
    percentile position (which deterministically drives band placement)
    behave as a calibrated confidence that a word is genuinely related?

    THIS IS A DELIBERATE METHODOLOGICAL CHOICE, not the only valid ECE
    formulation for this task — a reviewer should read it as a proxy
    confidence derived from rank percentile, not a model-native probability:

      confidence_i = 1 - (actual_rank_i / vocab_size)  [higher = ranked closer to the secret]
      outcome_i = tier_i in {"near", "mid"}  [ground truth: genuinely related vs authored decoy]

    Delegates to metrics.expected_calibration_error(confidences, outcomes, n_bins).
    """
    resolved = [r for r in records if r["actual_rank"] is not None]
    confidences = [1.0 - (r["actual_rank"] / vocab_size) for r in resolved]
    outcomes = [r["tier"] in _RELEVANT_TIERS for r in resolved]
    return expected_calibration_error(confidences, outcomes, n_bins)
