from __future__ import annotations

"""
Step 1b -- objective-alignment sweep (spec-hinglish-diagnostic-sweep.md).
Takes the WINNING Step 1a capacity-control config and layers on two
ranking-aware variants, holding capacity method fixed so any delta is
attributable to the objective, not capacity:

  obj_hard_neg        -- mined hard negatives (hard_negatives.py) added as
                          an explicit MNRL "negative" column.
  obj_larger_batch     -- batch_size doubled (more in-batch negatives per
                          anchor, still the default random negatives).
  obj_hard_neg_larger  -- both combined.

Run (after editing WINNER below to Step 1a's result):
    uv run python -m evals.finetune.step1b_objective_sweep
"""

import json
from dataclasses import replace
from pathlib import Path

from evals.finetune.run_sweep import run_sweep
from evals.finetune.train_lib import TrainConfig

DATA_DIR = Path(__file__).parent / "data"

# Step 1a winner (full sweep table: data/method_sweep_results.jsonl):
# LoRA r=8, lr=2e-4, 4 epochs -- dim1_test 0.6339 vs baseline 0.4350
# (CI-significant, delta_ci=[+0.033,+0.377]), regression floor 7 fixed/3
# broken (net +4, best of all 13 swept configs), dim2 pass-rate 0.688
# (CI-significant, 5 fixed/0 broken -- zero regression on cross-language).
WINNER_KWARGS: dict = {
    "method": "lora",
    "lora_r": 8,
    "learning_rate": 2e-4,
    "num_epochs": 4,
    "early_stopping_patience": 2,
}


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def build_configs(winner_kwargs: dict) -> list[TrainConfig]:
    hard_neg_records = _load_jsonl(DATA_DIR / "train_mnrl_pairs_hard_neg.jsonl")
    graded_records = _load_jsonl(DATA_DIR / "train_graded_pairs.jsonl")

    base = TrainConfig(name="obj_base", **winner_kwargs)
    return [
        replace(
            base, name="obj_hard_neg", mnrl_records=hard_neg_records, graded_records=graded_records
        ),
        replace(base, name="obj_larger_batch", batch_size=winner_kwargs.get("batch_size", 16) * 2),
        replace(
            base,
            name="obj_hard_neg_larger_batch",
            mnrl_records=hard_neg_records,
            graded_records=graded_records,
            batch_size=winner_kwargs.get("batch_size", 16) * 2,
        ),
    ]


if __name__ == "__main__":
    if not WINNER_KWARGS:
        raise SystemExit("Set WINNER_KWARGS to Step 1a's winning config before running this sweep.")
    results = run_sweep(build_configs(WINNER_KWARGS))
    print(f"\n{len(results)} new configs run this session.")
