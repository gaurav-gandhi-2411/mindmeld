from __future__ import annotations

"""
Regression test for the load_best_model_at_end LoRA bug (P0, found
2026-07-19, docs/known-limitations.md entry 21).

transformers.Trainer._load_best_model() branches on
`_is_peft_model(self.model)`, but for SentenceTransformerTrainer
`self.model` is the OUTER SentenceTransformer container, never the nested
PeftModel -- so the branch is always False for a LoRA run, and the
Trainer's checkpoint-loading logic falls through to a path that expects a
full model.safetensors file, which a LoRA checkpoint (adapter-only) never
has. Net effect: `load_best_model_at_end=True` silently keeps the LAST
epoch's weights instead of the tracked-best epoch's weights, with no
error or warning.

`train_lib._load_best_lora_checkpoint()` fixes this by explicitly
restoring the best checkpoint's adapter weights via
`peft.set_peft_model_state_dict` and verifying the reload reproduces the
trainer's own tracked-best dev score.

This test runs a REAL (small) LoRA training loop -- deliberately tiny
(20 pairs, 2 epochs) to keep runtime reasonable while still exercising the
actual bug: the base model is real, actually trained, actually
checkpointed to disk, actually reloaded. A mock/unit-only test would not
have caught the original bug (it's a real interaction between
SentenceTransformerTrainer, PEFT, and the transformers Trainer's
checkpoint I/O), so this test doesn't try to fake that away.
"""

import json
from pathlib import Path

import pytest
from sentence_transformers import SentenceTransformer

from evals.finetune.train_lib import DATA_DIR, TrainConfig, run_training


def _load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture(scope="module")
def tiny_lora_run() -> dict:
    """One small, real LoRA training run, shared across assertions in this
    file (training is the expensive part; re-run it once, not per-test)."""
    mnrl_records = _load_jsonl(DATA_DIR / "train_mnrl_pairs.jsonl")[:20]
    graded_records = _load_jsonl(DATA_DIR / "train_graded_pairs.jsonl")[:20]

    cfg = TrainConfig(
        name="test_lora_best_checkpoint_regression",
        method="lora",
        lora_r=8,
        lora_alpha=16,
        num_epochs=2,
        batch_size=8,
        early_stopping_patience=5,  # never trigger early stop in a 2-epoch test run
        mnrl_records=mnrl_records,
        graded_records=graded_records,
    )
    return run_training(cfg)


def test_saved_model_dev_score_matches_tracked_best(tiny_lora_run: dict) -> None:
    """
    The actual regression test: reload the SAVED model from disk (exactly
    as any downstream consumer -- eval_model.py, benchmark_bakeoff.py --
    would) and confirm its dev score matches what the trainer claims is
    the best epoch, not merely whatever the last epoch happened to
    produce. Before the fix, this assertion could fail (the saved model's
    score matched the LAST epoch's dev_curve entry instead).
    """
    from evals.finetune.train_lib import _build_dev_evaluator

    saved_model = SentenceTransformer(tiny_lora_run["output_dir"])
    dev_evaluator = _build_dev_evaluator()
    result = dev_evaluator(saved_model)

    reloaded_score = result["dev_spearman_cosine"]
    tracked_best = tiny_lora_run["best_dev_spearman_cosine"]
    assert reloaded_score == pytest.approx(tracked_best, abs=1e-4), (
        f"saved model's actual dev score ({reloaded_score:.6f}) does not match "
        f"the trainer's tracked-best score ({tracked_best:.6f}) -- the "
        "load_best_model_at_end LoRA bug has regressed"
    )


def test_dev_curve_has_multiple_epochs(tiny_lora_run: dict) -> None:
    """Sanity check the fixture actually trained >1 epoch (a 1-epoch run
    can't distinguish 'best' from 'last' and would make the main assertion
    vacuous)."""
    epochs_evaluated = [e for e in tiny_lora_run["dev_curve"] if "eval_dev_spearman_cosine" in e]
    assert len(epochs_evaluated) >= 2
