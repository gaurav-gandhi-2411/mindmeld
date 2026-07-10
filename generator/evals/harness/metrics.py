from __future__ import annotations

"""Shared statistics helpers for the eval harness — no scipy dependency
(generator/pyproject.toml only declares numpy), so Spearman correlation is
implemented directly via rank-transform + Pearson correlation (mathematically
equivalent to scipy.stats.spearmanr with the default average-rank tie
handling).
"""

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
