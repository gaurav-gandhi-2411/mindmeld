from __future__ import annotations

"""
Step 1a -- capacity-control sweep (spec-hinglish-diagnostic-sweep.md).

Holds training DATA fixed at the v2 assembled set (data/train_{mnrl,graded}
_pairs.jsonl -- 756/1028 pairs, same as the already-reported, NOT-SHIPPED v2
retry) and varies ONLY the capacity-control method: this isolates whether
the v1/v2 regression was caused by the optimization method (full-parameter
fine-tune with no regularization) rather than data volume, which both prior
sessions changed instead.

`cap_full_replicate` reruns the EXACT v2 hyperparameters (method=full,
lr=2e-5, 4 epochs) through this sweep's own train_lib/eval harness purely as
a parity check against the already-reported 0.3244 held-out dim1_test
Spearman (ship_decision_report_v2.md) -- confirms train_lib.py reproduces
train.py's result before trusting any NEW config's number.

Run: uv run python -m evals.finetune.step1a_capacity_sweep
"""

from evals.finetune.run_sweep import run_sweep
from evals.finetune.train_lib import TrainConfig

WAVE_1 = [
    TrainConfig(name="cap_full_replicate", method="full", learning_rate=2e-5, num_epochs=4),
    TrainConfig(name="cap_full_lr5e-6", method="full", learning_rate=5e-6, num_epochs=4),
    TrainConfig(name="cap_full_lr1e-6", method="full", learning_rate=1e-6, num_epochs=4),
    TrainConfig(
        name="cap_freeze8_lr2e-5",
        method="freeze",
        freeze_n_layers=8,
        learning_rate=2e-5,
        num_epochs=4,
    ),
    TrainConfig(
        name="cap_freeze10_lr2e-5",
        method="freeze",
        freeze_n_layers=10,
        learning_rate=2e-5,
        num_epochs=4,
    ),
    TrainConfig(
        name="cap_lora_r8_lr1e-4", method="lora", lora_r=8, learning_rate=1e-4, num_epochs=4
    ),
    TrainConfig(
        name="cap_lora_r16_lr1e-4", method="lora", lora_r=16, learning_rate=1e-4, num_epochs=4
    ),
    TrainConfig(name="cap_head_only_lr1e-3", method="head_only", learning_rate=1e-3, num_epochs=4),
]

if __name__ == "__main__":
    results = run_sweep(WAVE_1)
    print(f"\n{len(results)} new configs run this session.")
