from __future__ import annotations

"""
Step 1e -- learning-curve diagnostic (spec-hinglish-diagnostic-sweep.md),
using the Step 1a winning config (LoRA r=8, lr=2e-4, 4 epochs). The 100%
point reuses the already-logged `cap_lora_r8_lr2e-4` result (same config,
same full dataset -- rerunning would be identical modulo nondeterminism
already controlled by seed=42) instead of retraining; only 25%/50% are run
fresh here.

Run: uv run python -m evals.finetune.step1e_learning_curve_driver
"""

import json
import random
from pathlib import Path

from evals.finetune.run_sweep import _load_baseline_records, run_one
from evals.finetune.step1b_objective_sweep import WINNER_KWARGS
from evals.finetune.train_lib import TrainConfig

DATA_DIR = Path(__file__).parent / "data"
SEED = 42


def _load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _subsample(records: list[dict], frac: float, seed: int) -> list[dict]:
    rng = random.Random(seed)
    k = round(len(records) * frac)
    return rng.sample(records, k)


def _existing_100pct_result() -> dict:
    for line in (DATA_DIR / "method_sweep_results.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec["name"] == "cap_lora_r8_lr2e-4":
            rec = dict(rec)
            rec["data_fraction"] = 1.0
            return rec
    raise RuntimeError("cap_lora_r8_lr2e-4 not found in method_sweep_results.jsonl")


if __name__ == "__main__":
    full_mnrl = _load_jsonl(DATA_DIR / "train_mnrl_pairs.jsonl")
    full_graded = _load_jsonl(DATA_DIR / "train_graded_pairs.jsonl")
    baseline_dim1, baseline_dim2 = _load_baseline_records()

    results = []
    for frac in (0.25, 0.5):
        mnrl_sub = _subsample(full_mnrl, frac, SEED)
        graded_sub = _subsample(full_graded, frac, SEED)
        cfg = TrainConfig(
            name=f"lc_winner_frac{int(frac * 100)}",
            mnrl_records=mnrl_sub,
            graded_records=graded_sub,
            **WINNER_KWARGS,
        )
        print(f"=== {cfg.name} (n_mnrl={len(mnrl_sub)}, n_graded={len(graded_sub)}) ===")
        record = run_one(cfg, baseline_dim1, baseline_dim2)
        record["data_fraction"] = frac
        results.append(record)
        print(f"  dim1_test={record['dim1_test_spearman']:.4f}")

    results.append(_existing_100pct_result())
    results.sort(key=lambda r: r["data_fraction"])

    curve_path = DATA_DIR / "lc_winner_learning_curve.json"
    curve_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    spearmans = [r["dim1_test_spearman"] for r in results]
    fractions = [r["data_fraction"] for r in results]
    rising = spearmans[-1] > spearmans[0] and spearmans == sorted(spearmans)
    verdict = (
        "RISING (data helps)"
        if rising
        else "FLAT/NOT MONOTONIC (method was the bottleneck, not data volume)"
    )
    print("\nLearning curve:")
    for f, s in zip(fractions, spearmans, strict=True):
        print(f"  {int(f * 100)}%: {s:.4f}")
    print(f"Verdict: {verdict}")
