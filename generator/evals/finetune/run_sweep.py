from __future__ import annotations

"""
Method-sweep runner (spec-hinglish-diagnostic-sweep.md Step 1). Trains each
TrainConfig in a supplied list, evaluates the resulting checkpoint on the
frozen held-out TEST split (eval_model.evaluate_model), computes a paired
bootstrap delta + regression floor against the off-the-shelf baseline
(bootstrap_ci.baseline_report's cached records), and appends one JSON record
per config to data/method_sweep_results.jsonl (append-only, resumable --
reruns skip any config name that already has a logged result unless
force=True).

Every result carries the full config + seed (already embedded in the
train_summary), so the sweep is rerunnable per-config from this log alone.
"""

import json
from pathlib import Path

from evals.finetune.bootstrap_ci import (
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import evaluate_model
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from evals.finetune.train_lib import TrainConfig, run_training

DATA_DIR = Path(__file__).parent / "data"
BASELINE_RECORDS_PATH = DATA_DIR / "baseline_holdout_records.json"
SWEEP_LOG_PATH = DATA_DIR / "method_sweep_results.jsonl"


def _load_baseline_records() -> tuple[list[dict], list[dict]]:
    if not BASELINE_RECORDS_PATH.exists():
        raise FileNotFoundError(
            f"{BASELINE_RECORDS_PATH} missing -- run "
            "`uv run python -m evals.finetune.bootstrap_ci` first"
        )
    data = json.loads(BASELINE_RECORDS_PATH.read_text(encoding="utf-8"))
    return data["dim1_test_records"], data["dim2_test_records"]


def _already_logged() -> set[str]:
    if not SWEEP_LOG_PATH.exists():
        return set()
    names = set()
    for line in SWEEP_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            names.add(json.loads(line)["name"])
    return names


def run_one(cfg: TrainConfig, baseline_dim1: list[dict], baseline_dim2: list[dict]) -> dict:
    train_summary = run_training(cfg)
    eval_result = evaluate_model(train_summary["output_dir"])

    dim1_delta = paired_bootstrap_dim1_delta(baseline_dim1, eval_result["dim1_test"]["records"])
    dim2_delta = paired_bootstrap_dim2_delta(baseline_dim2, eval_result["dim2_test"]["records"])
    dim1_floor = dim1_regression_floor(baseline_dim1, eval_result["dim1_test"]["records"])
    dim2_floor = dim2_regression_floor(baseline_dim2, eval_result["dim2_test"]["records"])

    record = {
        "name": cfg.name,
        "method": cfg.method,
        "hyperparams": train_summary["hyperparams"],
        "n_mnrl_pairs": train_summary["n_mnrl_pairs"],
        "n_graded_pairs": train_summary["n_graded_pairs"],
        "trainable_fraction": train_summary["trainable_fraction"],
        "n_trainable_params": train_summary["n_trainable_params"],
        "best_dev_spearman_cosine": train_summary["best_dev_spearman_cosine"],
        "dim1_test_spearman": eval_result["dim1_test"]["spearman_correlation"],
        "dim1_delta_vs_baseline": dim1_delta,
        "dim1_regression_floor": dim1_floor,
        "dim2_test_pass_rate": eval_result["dim2_test"]["pass_rate_scorching_or_hot"],
        "dim2_delta_vs_baseline": dim2_delta,
        "dim2_regression_floor": dim2_floor,
        "residual_weak_dim1_spearman": eval_result["residual_weak_dim1"]["spearman_correlation"],
        "residual_weak_dim2_pass_rate": eval_result["residual_weak_dim2"][
            "pass_rate_scorching_or_hot"
        ],
    }
    with SWEEP_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


def run_sweep(configs: list[TrainConfig], force: bool = False) -> list[dict]:
    baseline_dim1, baseline_dim2 = _load_baseline_records()
    done = set() if force else _already_logged()
    results = []
    for cfg in configs:
        if cfg.name in done:
            print(f"skip {cfg.name} (already logged)")
            continue
        print(f"=== running {cfg.name} (method={cfg.method}) ===")
        record = run_one(cfg, baseline_dim1, baseline_dim2)
        print(
            f"  dim1_test={record['dim1_test_spearman']:.4f} "
            f"delta_ci={record['dim1_delta_vs_baseline']['delta_ci_95']} "
            f"dim2_pass_rate={record['dim2_test_pass_rate']:.4f} "
            f"floor(fixed/broken)={record['dim1_regression_floor']['n_fixed']}/"
            f"{record['dim1_regression_floor']['n_broken']}"
        )
        results.append(record)
    return results
