from __future__ import annotations

"""
Re-verification: recompute dev<->test correlation + shipped-model bootstrap
CIs against the FINAL, published public_benchmark_staging/dim1_hien.json
content -- not the production evals/scenarios/*.json files
public_benchmark_analysis.py reuses.

Why this exists: the staging files were scrub-corrected (24 words swapped
across two review rounds) AFTER the original bake-off checkpoints were
computed. public_benchmark_analysis.py's numbers therefore describe the
PRE-swap word list, not what's actually being published. This script
re-resolves the 34-secret dim1 benchmark against the CURRENT staging file
for all 8 CANDIDATE_MODELS, reusing each model's already-cached full-vocab
embedding matrix (embed_vocab cache-hits -- no new model downloads or
inference, per the module docstring's "skip model loading entirely" on a
cache hit) so this is cheap despite touching every model.

dim2 is NOT recomputed here: dim2_pairs are (en_secret, hien_secret) name
tuples, and no secret NAME was ever swapped (only near/mid/far associate
WORDS) -- dim2 numbers are unaffected by the scrub fixes by construction.

Run: uv run python -m evals.finetune.public_benchmark_reverify
"""

import json
from pathlib import Path

import numpy as np

from evals.finetune.benchmark_bakeoff import CANDIDATE_MODELS, SHIPPED_MODEL
from evals.finetune.bootstrap_ci import (
    _dim1_by_secret,
    _dim1_spearman_for_secrets,
    bootstrap_dim1_spearman_ci,
)
from evals.finetune.eval_model import _model_override
from evals.finetune.public_benchmark_split import load_split
from evals.harness.dimension1_ranking import _resolve_actuals

DATA_DIR = Path(__file__).parent / "data"
STAGING_DIM1_HIEN = DATA_DIR / "public_benchmark_staging" / "dim1_hien.json"
OUT_PATH = DATA_DIR / "public_benchmark_reverify.json"


def _staging_records() -> list[dict]:
    return json.loads(STAGING_DIM1_HIEN.read_text(encoding="utf-8"))


def _dev_test_scores(
    dim1_records: list[dict], dev_secrets: list[str], test_secrets: list[str]
) -> dict:
    by_secret = _dim1_by_secret(dim1_records)
    dev_present = sorted(set(dev_secrets) & set(by_secret))
    test_present = sorted(set(test_secrets) & set(by_secret))
    return {
        "dev_score": _dim1_spearman_for_secrets(by_secret, dev_present),
        "test_score": _dim1_spearman_for_secrets(by_secret, test_present),
        "n_dev_secrets_resolved": len(dev_present),
        "n_test_secrets_resolved": len(test_present),
    }


def main() -> dict:
    split = load_split()
    dev_secrets, test_secrets = split["dev_secrets"], split["test_secrets"]
    raw_scenarios = _staging_records()

    per_model: dict[str, dict] = {}
    shipped_records: list[dict] | None = None
    for model_name in CANDIDATE_MODELS:
        with _model_override(model_name):
            resolved = _resolve_actuals(raw_scenarios, "hi-en")
        per_model[model_name] = _dev_test_scores(resolved, dev_secrets, test_secrets)
        if model_name == SHIPPED_MODEL:
            shipped_records = resolved
        print(
            f"[resolved] {model_name}: dev={per_model[model_name]['dev_score']:.4f} "
            f"test={per_model[model_name]['test_score']:.4f}"
        )

    valid = [
        m
        for m, v in per_model.items()
        if not (np.isnan(v["dev_score"]) or np.isnan(v["test_score"]))
    ]
    paired_dev = [per_model[m]["dev_score"] for m in valid]
    paired_test = [per_model[m]["test_score"] for m in valid]
    pearson_r = float(np.corrcoef(paired_dev, paired_test)[0, 1]) if len(valid) >= 3 else None

    all_34 = set(dev_secrets) | set(test_secrets)
    assert shipped_records is not None
    dev_set, test_set = set(dev_secrets), set(test_secrets)
    shipped_ci = {
        "full_34": bootstrap_dim1_spearman_ci(
            [r for r in shipped_records if r["secret"] in all_34]
        ),
        "dev_only": bootstrap_dim1_spearman_ci(
            [r for r in shipped_records if r["secret"] in dev_set]
        ),
        "test_only": bootstrap_dim1_spearman_ci(
            [r for r in shipped_records if r["secret"] in test_set]
        ),
    }

    result = {
        "source": "public_benchmark_staging/dim1_hien.json (post-scrub, published content)",
        "n_models_used": len(valid),
        "per_model_dev_test_scores": per_model,
        "dev_test_pearson_r": pearson_r,
        "prior_reported_pearson_r_pre_scrub_words": 0.8852940766818941,
        "shipped_model_bootstrap_ci": shipped_ci,
        "prior_reported_shipped_bootstrap_ci_pre_scrub_words": {
            "full_34_point": 0.657,
            "dev_only_point": 0.688,
            "test_only_point": 0.628,
        },
    }
    OUT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    prior_r = result["prior_reported_pearson_r_pre_scrub_words"]
    print(f"\nwrote {OUT_PATH}")
    print(f"dev<->test Pearson r (post-scrub words): {pearson_r} (was {prior_r} pre-scrub)")
    print(
        f"shipped full_34 dim1 Spearman (post-scrub words): "
        f"{shipped_ci['full_34']['point']} (was 0.657 pre-scrub)"
    )
    return result


if __name__ == "__main__":
    main()
