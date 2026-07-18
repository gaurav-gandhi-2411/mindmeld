from __future__ import annotations

"""
Learning-curve diagnostic (spec-hinglish-diagnostic-sweep.md Step 1e) --
"definitively answers the more-data question with evidence". Trains the
WINNING capacity-control config (Step 1a) on 25% / 50% / 100% of the fixed
v2 assembled data and plots held-out dim1_test Spearman vs. data size.

Verdict rule: RISING at 100% -> data volume genuinely helps, revisit data.
FLAT/FALLING -> the method (not volume) is the bottleneck -- consistent
with v1->v2's own finding that +43% more data made every held-out metric
WORSE, which this curve either corroborates (still falling/flat once
capacity is controlled) or overturns (rising once capacity is controlled,
meaning v1/v2's regression really was an uncontrolled-capacity artifact that
masked a genuine data-volume benefit).

Subsampling is over the pooled MNRL/graded record lists (not per-source
stratified) -- a plain seeded random subsample of "how much training
signal", matching the spec's literal "25%/50%/100% of the data" framing.

Run: uv run python -m evals.finetune.learning_curve
"""

import json
import random
from pathlib import Path

from evals.finetune.run_sweep import _load_baseline_records, run_one
from evals.finetune.train_lib import TrainConfig

DATA_DIR = Path(__file__).parent / "data"
FRACTIONS = (0.25, 0.5, 1.0)
SEED = 42


def _subsample(records: list[dict], frac: float, seed: int) -> list[dict]:
    if frac >= 1.0:
        return records
    rng = random.Random(seed)
    k = round(len(records) * frac)
    return rng.sample(records, k)


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def run_learning_curve(
    base_config_kwargs: dict, mnrl_path: Path, graded_path: Path, name_prefix: str
) -> list[dict]:
    """base_config_kwargs: the WINNING Step 1a config's method/hyperparams
    (everything except name/mnrl_records/graded_records/mnrl_path/graded_path)."""
    full_mnrl = _load_jsonl(mnrl_path)
    full_graded = _load_jsonl(graded_path)
    baseline_dim1, baseline_dim2 = _load_baseline_records()

    results = []
    for frac in FRACTIONS:
        mnrl_sub = _subsample(full_mnrl, frac, SEED)
        graded_sub = _subsample(full_graded, frac, SEED)
        cfg = TrainConfig(
            name=f"{name_prefix}_frac{int(frac * 100)}",
            mnrl_records=mnrl_sub,
            graded_records=graded_sub,
            **base_config_kwargs,
        )
        print(f"=== {cfg.name} (n_mnrl={len(mnrl_sub)}, n_graded={len(graded_sub)}) ===")
        record = run_one(cfg, baseline_dim1, baseline_dim2)
        record["data_fraction"] = frac
        results.append(record)
        print(f"  dim1_test={record['dim1_test_spearman']:.4f}")

    curve_path = DATA_DIR / f"{name_prefix}_learning_curve.json"
    curve_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    spearmans = [r["dim1_test_spearman"] for r in results]
    verdict = (
        "RISING (data helps)"
        if spearmans[-1] > spearmans[0] and spearmans[-1] >= max(spearmans[:-1])
        else "FLAT/FALLING (method is the bottleneck, not data volume)"
    )
    print(f"\nLearning curve verdict: {verdict}")
    print(f"  25%: {spearmans[0]:.4f}  50%: {spearmans[1]:.4f}  100%: {spearmans[2]:.4f}")
    return results


if __name__ == "__main__":
    import sys

    print(
        "This module is a library -- invoke run_learning_curve(...) from a "
        "driver script once Step 1a's winning config is known.",
        file=sys.stderr,
    )
    sys.exit(1)
