from __future__ import annotations

"""
Step 1a wave 2 -- LoRA fine sweep. Wave 1 found LoRA (r=8/16, lr=1e-4) the
clear capacity-control winner: dim1_test 0.543-0.546 vs baseline 0.4350
(+0.108/+0.111), dim2 pass-rate 0.375->0.625, regression floor net +2 (4
fixed/2 broken) -- but the paired-bootstrap CI lower bound sat just barely
below zero (-0.022 to -0.024), a hair short of CI-significant. Dev-curve for
both was STILL RISING at epoch 4 with no early-stop trigger (patience=2
never fired), so this wave tests: more epochs (does test keep improving or
start to overfit like the full-finetune runs did?), higher rank (r=32), and
an LR bracket around 1e-4.

Run: uv run python -m evals.finetune.step1a_wave2_lora_fine
"""

from evals.finetune.run_sweep import run_sweep
from evals.finetune.train_lib import TrainConfig

WAVE_2 = [
    TrainConfig(
        name="cap_lora_r8_lr1e-4_ep8",
        method="lora",
        lora_r=8,
        learning_rate=1e-4,
        num_epochs=8,
        early_stopping_patience=3,
    ),
    TrainConfig(
        name="cap_lora_r16_lr1e-4_ep8",
        method="lora",
        lora_r=16,
        learning_rate=1e-4,
        num_epochs=8,
        early_stopping_patience=3,
    ),
    TrainConfig(
        name="cap_lora_r32_lr1e-4", method="lora", lora_r=32, learning_rate=1e-4, num_epochs=4
    ),
    TrainConfig(
        name="cap_lora_r8_lr2e-4", method="lora", lora_r=8, learning_rate=2e-4, num_epochs=4
    ),
    TrainConfig(
        name="cap_lora_r8_lr5e-5", method="lora", lora_r=8, learning_rate=5e-5, num_epochs=4
    ),
]

if __name__ == "__main__":
    results = run_sweep(WAVE_2)
    print(f"\n{len(results)} new configs run this session.")
