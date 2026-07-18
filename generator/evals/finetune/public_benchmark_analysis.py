from __future__ import annotations

"""
Analysis for the 34-secret public benchmark's dev/test split
(evals/finetune/public_benchmark_split.py, spec-hinglish-benchmark.md
Phase 1c): (1) does the dev half predict the test half across models
(the "does this split fix the old n=16 problem, where dev<->test
correlation was ~0.12" question), and (2) bootstrap 95% CIs for the
shipped model on the full 34-secret benchmark, dev-only, and test-only.

Uses ONLY data already on disk -- the 8-model bake-off checkpoints
(evals/finetune/data/bakeoff_raw/*.json, produced by
evals/finetune/benchmark_bakeoff.py, read-only reference here, never
modified) -- no model is re-run, no embedding call is made.

Dev/test correlation methodology: for each of the N models with a valid
checkpoint, slice its dim1_records (which cover all 42 test-set secrets --
8 production + 34 benchmark-supplement) down to just the 34 benchmark
secrets, split by this module's dev_secrets/test_secrets, and compute each
half's dim1 Spearman via evals.finetune.bootstrap_ci's existing
`_dim1_by_secret`/`_dim1_spearman_for_secrets` helpers (reused, not
reimplemented -- same helpers bootstrap_ci.py itself uses for the
per-secret-cluster Spearman it bootstraps). This yields N (dev_score,
test_score) pairs, one per model. The Pearson correlation across those N
pairs (np.corrcoef on the RAW scores, not rank-transformed -- explicitly
Pearson, not Spearman, since N is small (<=8) and the metric relationship
across MODELS is what's being tested, not a per-item rank relationship) is
the reported dev<->test correlation number.

If fewer than all 8 CANDIDATE_MODELS have a valid checkpoint on disk (e.g.
a background bake-off run is still in flight), this module proceeds with
however many ARE available and reports `n_models_used` explicitly rather
than blocking or silently estimating.

Run: uv run python -m evals.finetune.public_benchmark_analysis
Output: evals/finetune/data/public_benchmark_analysis.json
"""

import json
from pathlib import Path

import numpy as np

from evals.finetune.benchmark_bakeoff import CANDIDATE_MODELS, SHIPPED_MODEL, _load_valid_checkpoint
from evals.finetune.bootstrap_ci import (
    _dim1_by_secret,
    _dim1_spearman_for_secrets,
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
)
from evals.finetune.public_benchmark_split import load_split

DATA_DIR = Path(__file__).parent / "data"
OUT_PATH = DATA_DIR / "public_benchmark_analysis.json"


def _dev_test_scores_for_model(
    dim1_records: list[dict], dev_secrets: list[str], test_secrets: list[str]
) -> dict:
    """
    One model's (dev_score, test_score) pair on this benchmark's dim1
    Spearman, restricted to secrets that actually resolved (have a
    non-null actual_rank) -- see module docstring for the reused helpers.
    """
    by_secret = _dim1_by_secret(dim1_records)  # already drops unresolved records
    dev_present = sorted(set(dev_secrets) & set(by_secret))
    test_present = sorted(set(test_secrets) & set(by_secret))
    dev_score = _dim1_spearman_for_secrets(by_secret, dev_present)
    test_score = _dim1_spearman_for_secrets(by_secret, test_present)
    return {
        "dev_score": dev_score,
        "test_score": test_score,
        "n_dev_secrets_resolved": len(dev_present),
        "n_test_secrets_resolved": len(test_present),
    }


def dev_test_correlation(split: dict) -> dict:
    """
    Compute (dev_score, test_score) for every model with a valid bake-off
    checkpoint, then the Pearson correlation of those pairs across models.
    """
    dev_secrets, test_secrets = split["dev_secrets"], split["test_secrets"]

    per_model: dict[str, dict] = {}
    for model_name in CANDIDATE_MODELS:
        checkpoint = _load_valid_checkpoint(model_name)
        if checkpoint is None:
            continue
        per_model[model_name] = _dev_test_scores_for_model(
            checkpoint["dim1_records"], dev_secrets, test_secrets
        )

    # Only pair up models where BOTH halves produced a valid (non-NaN) score.
    valid_models = [
        name
        for name, v in per_model.items()
        if not (np.isnan(v["dev_score"]) or np.isnan(v["test_score"]))
    ]
    paired_dev = [per_model[m]["dev_score"] for m in valid_models]
    paired_test = [per_model[m]["test_score"] for m in valid_models]

    pearson_r: float | None
    if len(valid_models) >= 3 and np.std(paired_dev) > 0 and np.std(paired_test) > 0:
        pearson_r = float(np.corrcoef(paired_dev, paired_test)[0, 1])
    else:
        pearson_r = None

    return {
        "n_models_in_candidate_list": len(CANDIDATE_MODELS),
        "n_models_used": len(valid_models),
        "models_used": valid_models,
        "models_missing_checkpoint": sorted(set(CANDIDATE_MODELS) - set(per_model)),
        "per_model_dev_test_scores": per_model,
        "correlation_method": "pearson",
        "dev_test_pearson_r": pearson_r,
        "old_n16_baseline_correlation": 0.12,
        "materially_improves_on_0_12": (
            None if pearson_r is None else bool(pearson_r > 0.12 + 0.10)
        ),
    }


def _filter_by_secret(records: list[dict], secrets: set[str], key: str) -> list[dict]:
    return [r for r in records if r[key] in secrets]


def shipped_model_bootstrap_cis(split: dict) -> dict | None:
    """
    Bootstrap 95% CIs for the shipped model's performance on the full
    34-secret benchmark, dev-only, and test-only -- sliced from its
    already-computed bake-off checkpoint (no re-embedding). Returns None
    if the shipped model's checkpoint isn't on disk yet (e.g. a background
    bake-off run hasn't finished it in this session).
    """
    checkpoint = _load_valid_checkpoint(SHIPPED_MODEL)
    if checkpoint is None:
        return None

    dev_secrets, test_secrets = set(split["dev_secrets"]), set(split["test_secrets"])
    all_34 = dev_secrets | test_secrets

    dim1 = checkpoint["dim1_records"]
    dim2 = checkpoint["dim2_records"]

    return {
        "dim1_spearman": {
            "full_34": bootstrap_dim1_spearman_ci(_filter_by_secret(dim1, all_34, "secret")),
            "dev_only": bootstrap_dim1_spearman_ci(_filter_by_secret(dim1, dev_secrets, "secret")),
            "test_only": bootstrap_dim1_spearman_ci(
                _filter_by_secret(dim1, test_secrets, "secret")
            ),
        },
        "dim2_pass_rate": {
            "full_34": bootstrap_dim2_pass_rate_ci(_filter_by_secret(dim2, all_34, "hien_secret")),
            "dev_only": bootstrap_dim2_pass_rate_ci(
                _filter_by_secret(dim2, dev_secrets, "hien_secret")
            ),
            "test_only": bootstrap_dim2_pass_rate_ci(
                _filter_by_secret(dim2, test_secrets, "hien_secret")
            ),
        },
    }


def main() -> dict:
    split = load_split()
    result = {
        "split_seed": split["seed"],
        "dev_test_correlation": dev_test_correlation(split),
        "shipped_model_bootstrap_ci": shipped_model_bootstrap_cis(split),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    dtc = result["dev_test_correlation"]
    print(f"dev<->test Pearson r: {dtc['dev_test_pearson_r']} (n_models={dtc['n_models_used']})")
    if dtc["models_missing_checkpoint"]:
        print(f"missing checkpoints (not used): {dtc['models_missing_checkpoint']}")
    if result["shipped_model_bootstrap_ci"] is None:
        print(f"shipped model ({SHIPPED_MODEL}) checkpoint not found -- skipped bootstrap CIs")
    return result


if __name__ == "__main__":
    main()
