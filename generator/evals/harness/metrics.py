from __future__ import annotations

"""Shared statistics helpers for the eval harness — no scipy dependency
(generator/pyproject.toml only declares numpy), so Spearman correlation is
implemented directly via rank-transform + Pearson correlation (mathematically
equivalent to scipy.stats.spearmanr with the default average-rank tie
handling).
"""

import math

import numpy as np


def rankdata(values: list[float]) -> np.ndarray:
    """Rank-transform `values` (1-based), averaging ranks across ties.

    Mirrors scipy.stats.rankdata(method="average"). E.g. [10, 20, 20, 30]
    -> [1.0, 2.5, 2.5, 4.0].
    """
    arr = np.asarray(values, dtype=np.float64)
    order = arr.argsort(kind="mergesort")
    ranks = np.empty(len(arr), dtype=np.float64)
    sorted_arr = arr[order]

    i = 0
    n = len(arr)
    while i < n:
        j = i
        while j + 1 < n and sorted_arr[j + 1] == sorted_arr[i]:
            j += 1
        # Positions i..j (inclusive) are tied; average rank is the mean of
        # the 1-based rank range [i+1, j+1].
        avg_rank = (i + 1 + j + 1) / 2.0
        ranks[order[i : j + 1]] = avg_rank
        i = j + 1
    return ranks


def spearman_correlation(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation between `x` and `y`.

    Returns NaN if either input has zero variance (undefined correlation) —
    callers must handle NaN explicitly rather than silently getting 0.0,
    which would misleadingly imply "no correlation" instead of "undefined".
    """
    if len(x) != len(y) or len(x) < 2:
        return float("nan")
    rx = rankdata(x)
    ry = rankdata(y)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def dcg_gain(relevance: float) -> float:
    """2^relevance - 1, the standard exponential DCG gain function."""
    return 2.0**relevance - 1.0


def ndcg_from_judged(ranked_judged: list[tuple[int, float]], k: int) -> float | None:
    """NDCG@k over a SPARSE-JUDGMENT set: only items with a known relevance
    grade are scored (standard practice when most of the candidate space is
    unjudged — treating unjudged items as irrelevant would bias results).

    ranked_judged: list of (rank, relevance) pairs for ONE query's judged
    items. rank = 1-based position in the system's full ranking. relevance
    = graded relevance (0 = not relevant).

    DCG@k = sum over judged items with rank <= k of dcg_gain(relevance) / log2(rank + 1)
    IDCG@k = ideal DCG@k assuming the judged items' relevance grades are
    packed into ranks 1..min(k, n_judged), highest relevance first:
        IDCG@k = sum_{i=1}^{min(k, n)} dcg_gain(sorted_desc(relevances)[i-1]) / log2(i + 1)
    NDCG@k = DCG@k / IDCG@k. Returns None if IDCG@k == 0 (no judged item
    with positive relevance — NDCG is undefined, not zero, in that case).
    """
    if not ranked_judged:
        return None
    dcg = sum(dcg_gain(rel) / math.log2(rank + 1) for rank, rel in ranked_judged if rank <= k)
    n = len(ranked_judged)
    sorted_relevances = sorted((rel for _, rel in ranked_judged), reverse=True)
    m = min(k, n)
    idcg = sum(dcg_gain(sorted_relevances[i]) / math.log2(i + 2) for i in range(m))
    if idcg == 0:
        return None
    return dcg / idcg


def mean_reciprocal_rank(ranks: list[int | None]) -> float:
    """Mean of 1/rank over entries where rank is not None (a None entry
    means that query had no relevant item at all and is EXCLUDED from the
    mean, not treated as 0 — zero-filling would bias the mean downward for
    reasons unrelated to model quality). Returns NaN if every entry is None.
    """
    valid = [r for r in ranks if r is not None]
    if not valid:
        return float("nan")
    return float(np.mean([1.0 / r for r in valid]))


def expected_calibration_error(
    confidences: list[float], outcomes: list[bool], n_bins: int = 10
) -> dict:
    """Standard equal-width-bin ECE. confidences must be in [0,1].
    bin_idx = min(int(confidence * n_bins), n_bins - 1) for each item (so a
    confidence of exactly 1.0 lands in the last bin, not an out-of-range
    n_bins-th bin). Within each non-empty bin: mean_confidence, mean_outcome
    (fraction True). ECE = sum over non-empty bins of (bin_count / total) *
    abs(mean_confidence - mean_outcome).
    Returns {"ece": float, "n_bins_used": int, "bins": [{"bin_lo": float,
    "bin_hi": float, "n": int, "mean_confidence": float, "mean_outcome": float}, ...]}
    (bins list only includes non-empty bins, sorted by bin_lo).
    Returns {"ece": None, "n_bins_used": 0, "bins": []} if confidences is empty.
    """
    if not confidences:
        return {"ece": None, "n_bins_used": 0, "bins": []}
    by_bin: dict[int, list[tuple[float, bool]]] = {}
    for c, o in zip(confidences, outcomes, strict=True):
        bin_idx = min(int(c * n_bins), n_bins - 1)
        by_bin.setdefault(bin_idx, []).append((c, o))

    total = len(confidences)
    ece = 0.0
    bins = []
    for bin_idx in sorted(by_bin):
        items = by_bin[bin_idx]
        n = len(items)
        mean_confidence = sum(c for c, _ in items) / n
        mean_outcome = sum(1.0 if o else 0.0 for _, o in items) / n
        ece += (n / total) * abs(mean_confidence - mean_outcome)
        bins.append(
            {
                "bin_lo": bin_idx / n_bins,
                "bin_hi": (bin_idx + 1) / n_bins,
                "n": n,
                "mean_confidence": mean_confidence,
                "mean_outcome": mean_outcome,
            }
        )
    return {"ece": ece, "n_bins_used": len(by_bin), "bins": bins}


def top_weighted_correlation(expected_ordinal: list[float], actual_rank: list[float]) -> float:
    """Top-emphasising rank correlation: weighted Pearson correlation
    between rank-transformed(expected_ordinal) and rank-transformed(actual_rank)
    (reuse `rankdata`, same rank-transform as `spearman_correlation`), where
    each record i is weighted by w_i = 1 / log2(actual_rank[i] + 1) — using
    the RAW actual_rank (not its rank-transform) as the weight source, so
    weight concentrates on records whose target word truly landed near the
    top of the vocabulary ranking (rank 1 gets far more weight than rank
    9000). This directly operationalizes the program's core finding: users
    only perceive the top of the ranking, so a top-of-list error should
    dominate the correlation far more than a tail error.

    Weighted Pearson: for weights w, values x, y:
      wmean_x = sum(w*x)/sum(w); wmean_y = sum(w*y)/sum(w)
      wcov = sum(w*(x-wmean_x)*(y-wmean_y)) / sum(w)
      wvar_x = sum(w*(x-wmean_x)**2) / sum(w); wvar_y likewise
      corr = wcov / sqrt(wvar_x * wvar_y)
    Returns NaN if len(x) < 2, sum(w) == 0, wvar_x == 0, or wvar_y == 0.
    """
    if len(expected_ordinal) != len(actual_rank) or len(expected_ordinal) < 2:
        return float("nan")
    x = rankdata(expected_ordinal)
    y = rankdata(actual_rank)
    raw_rank = np.asarray(actual_rank, dtype=np.float64)
    w = 1.0 / np.log2(raw_rank + 1.0)
    sw = float(np.sum(w))
    if sw == 0:
        return float("nan")
    wmean_x = np.sum(w * x) / sw
    wmean_y = np.sum(w * y) / sw
    wcov = np.sum(w * (x - wmean_x) * (y - wmean_y)) / sw
    wvar_x = np.sum(w * (x - wmean_x) ** 2) / sw
    wvar_y = np.sum(w * (y - wmean_y) ** 2) / sw
    if wvar_x == 0 or wvar_y == 0:
        return float("nan")
    return float(wcov / np.sqrt(wvar_x * wvar_y))
