from __future__ import annotations

"""
Objective-alignment check (spec-hinglish-diagnostic-sweep.md Step 1b, second
half): "verify the training objective's improvement actually correlates
with held-out Spearman -- if train-loss drops but Spearman doesn't move, the
objective is misaligned."

Reads every logged config in data/method_sweep_results.jsonl (any wave) and
correlates each config's DEV-side training signal (best_dev_spearman_cosine
-- the metric the trainer's early-stopping/checkpoint-selection actually
optimizes) against its held-out dim1_test_spearman. A weak or negative
correlation across the sweep is itself the diagnostic finding: the thing the
training loop is selecting checkpoints on does not track what the game
actually needs, independent of which capacity-control method is used.

Run: uv run python -m evals.finetune.objective_alignment_check
"""

import json
from pathlib import Path

from evals.harness.metrics import spearman_correlation

DATA_DIR = Path(__file__).parent / "data"
SWEEP_LOG_PATH = DATA_DIR / "method_sweep_results.jsonl"


def load_all_runs() -> list[dict]:
    if not SWEEP_LOG_PATH.exists():
        return []
    return [
        json.loads(line)
        for line in SWEEP_LOG_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def dev_vs_test_correlation() -> dict:
    runs = load_all_runs()
    dev = [
        r["best_dev_spearman_cosine"] for r in runs if r.get("best_dev_spearman_cosine") is not None
    ]
    test = [
        r["dim1_test_spearman"]
        for r in runs
        if r.get("best_dev_spearman_cosine") is not None and r["dim1_test_spearman"] is not None
    ]
    names = [
        r["name"]
        for r in runs
        if r.get("best_dev_spearman_cosine") is not None and r["dim1_test_spearman"] is not None
    ]
    corr = spearman_correlation(dev, test) if len(dev) == len(test) and len(dev) >= 2 else None
    return {
        "n_configs": len(names),
        "config_names": names,
        "dev_spearman_values": dev,
        "test_spearman_values": test,
        "dev_vs_test_spearman_correlation": corr,
        "objective_misaligned": (corr is not None and corr < 0.3),
        "interpretation": (
            "dev-side checkpoint-selection metric does NOT reliably predict held-out "
            "test performance across this sweep -- the training objective/checkpoint "
            "selection is misaligned with the actual game-relevant metric"
            if (corr is not None and corr < 0.3)
            else "dev-side metric tracks held-out test reasonably well across this sweep"
            if corr is not None
            else "insufficient logged runs to compute a correlation"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(dev_vs_test_correlation(), indent=2))
