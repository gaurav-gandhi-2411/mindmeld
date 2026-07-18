from __future__ import annotations

"""
Bootstrap confidence intervals for the held-out hi-en eval (spec-hinglish-
diagnostic-sweep.md, Step 0 — "trust the ruler before trusting any result").

IMPORTANT CORRECTION vs the spec's literal wording: the spec says "bootstrap
a CI on the baseline 0.639 held-out Spearman". 0.639 is NOT a held-out
number — it is off-the-shelf's score on the FULL 25-secret/227-scenario
PRODUCTION dim1 set (evals/reports/baseline_report.md), which includes
secrets that are in this pipeline's train/dev split and therefore cannot be
used as a held-out comparator. Both ship-decision reports
(data/ship_decision_report{,_v2}.md) already established the correct
apples-to-apples number: dim1_test Spearman restricted to the 16 frozen
TEST secrets (8 of which carry dim1 scenarios, n=73) = 0.4350. This module
bootstraps a CI on THAT number, not 0.639. See data/ship_decision_report_v2.md
"SHIP DECISION" section for the prior precedent of this same correction.

Two CIs are computed:
  1. Marginal CI on a single model's dim1_test Spearman / dim2_test pass-rate
     — cluster-bootstrap by SECRET (not by scenario), because scenarios
     within a secret are not independent draws (they share the same secret
     embedding / rank table). n=8 secrets for dim1, n=16 for dim2 — the
     bootstrap resamples at the level that is actually i.i.d.
  2. Paired-difference CI between two models evaluated on the SAME held-out
     secrets — resample secret indices ONCE per bootstrap iteration and
     apply the same resample to both models' per-secret record groups. This
     is a paired bootstrap (lower variance, more powerful than comparing two
     independent marginal CIs) and is the correct test for "does candidate
     beat baseline" since both are scored on identical items.

Run: uv run python -m evals.finetune.bootstrap_ci
"""

import json
from pathlib import Path

import numpy as np

from evals.finetune.eval_model import OFF_THE_SHELF_MODEL, evaluate_model
from evals.harness.metrics import spearman_correlation

DATA_DIR = Path(__file__).parent / "data"
N_BOOT = 10000
SEED = 42
_TIER_ORDINAL = {"near": 1, "mid": 2, "far": 3}


def _dim1_by_secret(records: list[dict]) -> dict[str, list[dict]]:
    by_secret: dict[str, list[dict]] = {}
    for r in records:
        if r["actual_rank"] is None:
            continue
        by_secret.setdefault(r["secret"], []).append(r)
    return by_secret


def _dim1_spearman_for_secrets(by_secret: dict[str, list[dict]], secrets: list[str]) -> float:
    recs: list[dict] = []
    for s in secrets:
        recs.extend(by_secret[s])
    expected = [_TIER_ORDINAL[r["tier"]] for r in recs]
    actual = [r["actual_rank"] for r in recs]
    return spearman_correlation(expected, actual)


def bootstrap_dim1_spearman_ci(records: list[dict], n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    by_secret = _dim1_by_secret(records)
    secrets = sorted(by_secret)
    point = _dim1_spearman_for_secrets(by_secret, secrets)
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        val = _dim1_spearman_for_secrets(by_secret, resample)
        if not np.isnan(val):
            samples.append(val)
    lo, hi = (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))
    return {
        "point": point,
        "ci_95": [lo, hi],
        "n_clusters": len(secrets),
        "n_scenarios": sum(len(v) for v in by_secret.values()),
        "n_valid_bootstrap_draws": len(samples),
        "std": float(np.std(samples)) if samples else None,
    }


def paired_bootstrap_dim1_delta(
    baseline_records: list[dict],
    candidate_records: list[dict],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    base_by_secret = _dim1_by_secret(baseline_records)
    cand_by_secret = _dim1_by_secret(candidate_records)
    secrets = sorted(set(base_by_secret) & set(cand_by_secret))
    missing = set(base_by_secret) ^ set(cand_by_secret)
    base_point = _dim1_spearman_for_secrets(base_by_secret, secrets)
    cand_point = _dim1_spearman_for_secrets(cand_by_secret, secrets)
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        b = _dim1_spearman_for_secrets(base_by_secret, resample)
        c = _dim1_spearman_for_secrets(cand_by_secret, resample)
        if not (np.isnan(b) or np.isnan(c)):
            deltas.append(c - b)
    lo, hi = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    return {
        "baseline_point": base_point,
        "candidate_point": cand_point,
        "delta_point": cand_point - base_point,
        "delta_ci_95": [lo, hi],
        "ci_significant_improvement": lo > 0,
        "ci_significant_regression": hi < 0,
        "n_clusters": len(secrets),
        "secret_mismatch": sorted(missing) if missing else None,
        "n_valid_bootstrap_draws": len(deltas),
    }


def _dim2_by_pair(records: list[dict]) -> list[dict]:
    return [r for r in records if r["resolution_error"] is None]


def bootstrap_dim2_pass_rate_ci(
    records: list[dict], n_boot: int = N_BOOT, seed: int = SEED
) -> dict:
    resolved = _dim2_by_pair(records)
    n = len(resolved)
    consistent = np.array([1.0 if r["consistent"] else 0.0 for r in resolved])
    point = float(consistent.mean()) if n else None
    rng = np.random.default_rng(seed)
    idx_all = np.arange(n)
    samples = []
    for _ in range(n_boot):
        idx = rng.choice(idx_all, size=n, replace=True)
        samples.append(float(consistent[idx].mean()))
    lo, hi = (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))
    return {
        "point": point,
        "ci_95": [lo, hi],
        "n_pairs": n,
    }


def paired_bootstrap_dim2_delta(
    baseline_records: list[dict],
    candidate_records: list[dict],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    base = _dim2_by_pair(baseline_records)
    cand = _dim2_by_pair(candidate_records)
    base_key = {(r["en_secret"], r["hien_secret"]): r["consistent"] for r in base}
    cand_key = {(r["en_secret"], r["hien_secret"]): r["consistent"] for r in cand}
    pairs = sorted(set(base_key) & set(cand_key))
    base_arr = np.array([1.0 if base_key[p] else 0.0 for p in pairs])
    cand_arr = np.array([1.0 if cand_key[p] else 0.0 for p in pairs])
    n = len(pairs)
    rng = np.random.default_rng(seed)
    idx_all = np.arange(n)
    deltas = []
    for _ in range(n_boot):
        idx = rng.choice(idx_all, size=n, replace=True)
        deltas.append(float(cand_arr[idx].mean() - base_arr[idx].mean()))
    lo, hi = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    return {
        "baseline_point": float(base_arr.mean()) if n else None,
        "candidate_point": float(cand_arr.mean()) if n else None,
        "delta_point": float(cand_arr.mean() - base_arr.mean()) if n else None,
        "delta_ci_95": [lo, hi],
        "ci_significant_improvement": lo > 0,
        "ci_significant_regression": hi < 0,
        "n_pairs": n,
    }


def baseline_report() -> dict:
    result = evaluate_model(OFF_THE_SHELF_MODEL)
    dim1_ci = bootstrap_dim1_spearman_ci(result["dim1_test"]["records"])
    dim2_ci = bootstrap_dim2_pass_rate_ci(result["dim2_test"]["records"])
    out = {
        "model": OFF_THE_SHELF_MODEL,
        "note": (
            "0.639 (spec's quoted figure) is the FULL 25-secret production dim1 set "
            "score, not a held-out number -- see module docstring. The correct "
            "held-out TEST comparator is dim1_test below."
        ),
        "dim1_test_spearman": dim1_ci,
        "dim2_test_pass_rate": dim2_ci,
    }
    (DATA_DIR / "baseline_holdout_ci.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    (DATA_DIR / "baseline_holdout_records.json").write_text(
        json.dumps(
            {
                "dim1_test_records": result["dim1_test"]["records"],
                "dim2_test_records": result["dim2_test"]["records"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


if __name__ == "__main__":
    out = baseline_report()
    print(json.dumps(out, indent=2))
