from __future__ import annotations

"""
SBERT contrastive fine-tune of l3cube-pune/indic-sentence-bert-nli on
assembled Hinglish training data (assemble_data.py output).

Two loss objectives trained jointly (spec: "MultipleNegativesRankingLoss
... and/or CosineSimilarityLoss for graded pairs"):
  - "mnrl"   dataset (anchor, positive)              -> MultipleNegativesRankingLoss
  - "graded" dataset (sentence1, sentence2, score)   -> CosineSimilarityLoss

Conservative hyperparams (spec: "over-training is the enemy"): low LR, few
epochs, early-stopping on a DEV evaluator built from dim1_hien.json records
restricted to the frozen DEV-split secrets ONLY (never test, never train —
see split.py). The dev Spearman curve is logged and dumped so the training
run is inspectable, but it is NEVER reported as a result — only the TEST
split (eval_model.py, run after training) produces reportable numbers.

Local CPU only, $0, no API key. Base checkpoint is already cached locally
under ~/.cache/huggingface (downloaded during the original bake-off), so
this run makes no network calls either.

Run: uv run python -m evals.finetune.train
Output: evals/finetune/model/  (best checkpoint by dev spearman_cosine)
        evals/finetune/data/dev_curve.json
"""

import json
import random
from pathlib import Path

import numpy as np
import torch
from datasets import Dataset
from sentence_transformers import (
    SentenceTransformer,
    SentenceTransformerTrainer,
    SentenceTransformerTrainingArguments,
)
from sentence_transformers.evaluation import EmbeddingSimilarityEvaluator
from sentence_transformers.losses import CosineSimilarityLoss, MultipleNegativesRankingLoss
from transformers import EarlyStoppingCallback

from evals.finetune.eval_model import OFF_THE_SHELF_MODEL
from evals.finetune.split import load_split

SEED = 42
DATA_DIR = Path(__file__).parent / "data"
SCENARIOS_PATH = Path(__file__).parent.parent / "scenarios" / "dim1_hien.json"
OUTPUT_MODEL_DIR = Path(__file__).parent / "model"
CHECKPOINT_DIR = Path(__file__).parent / "checkpoints"

TIER_SCORE = {"near": 0.85, "mid": 0.55, "far": 0.05}

NUM_EPOCHS = 4
LEARNING_RATE = 2e-5
BATCH_SIZE = 16
WARMUP_RATIO = 0.1
EARLY_STOPPING_PATIENCE = 2


def _set_all_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _build_dev_evaluator() -> EmbeddingSimilarityEvaluator:
    """Dev-only graded pairs from dim1_hien.json — DEV secrets exclusively.
    Used purely for early-stopping / checkpoint selection, never reported."""
    split = load_split()
    dev_secrets = set(split["dev_secrets"])
    records = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    dev_records = [r for r in records if r["secret"] in dev_secrets]

    s1 = [r["secret"] for r in dev_records]
    s2 = [r["word"] for r in dev_records]
    scores = [TIER_SCORE[r["tier"]] for r in dev_records]
    return EmbeddingSimilarityEvaluator(
        sentences1=s1, sentences2=s2, scores=scores, name="dev", show_progress_bar=False
    )


def train() -> dict:
    _set_all_seeds(SEED)

    mnrl_records = _load_jsonl(DATA_DIR / "train_mnrl_pairs.jsonl")
    graded_records = _load_jsonl(DATA_DIR / "train_graded_pairs.jsonl")

    mnrl_ds = Dataset.from_dict(
        {
            "anchor": [r["anchor"] for r in mnrl_records],
            "positive": [r["positive"] for r in mnrl_records],
        }
    )
    graded_ds = Dataset.from_dict(
        {
            "sentence1": [r["sentence1"] for r in graded_records],
            "sentence2": [r["sentence2"] for r in graded_records],
            "score": [r["score"] for r in graded_records],
        }
    )

    model = SentenceTransformer(OFF_THE_SHELF_MODEL)

    losses = {
        "mnrl": MultipleNegativesRankingLoss(model),
        "graded": CosineSimilarityLoss(model),
    }
    train_dataset = {"mnrl": mnrl_ds, "graded": graded_ds}

    dev_evaluator = _build_dev_evaluator()

    args = SentenceTransformerTrainingArguments(
        output_dir=str(CHECKPOINT_DIR),
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        warmup_ratio=WARMUP_RATIO,
        seed=SEED,
        data_seed=SEED,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_dev_spearman_cosine",
        greater_is_better=True,
        logging_steps=10,
        report_to=[],
    )

    trainer = SentenceTransformerTrainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        loss=losses,
        evaluator=dev_evaluator,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=EARLY_STOPPING_PATIENCE)],
    )
    trainer.train()

    OUTPUT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(OUTPUT_MODEL_DIR))

    _dev_curve_keys = ("epoch", "step", "eval_dev_spearman_cosine", "loss")
    dev_curve = [
        {k: v for k, v in entry.items() if k in _dev_curve_keys}
        for entry in trainer.state.log_history
        if "eval_dev_spearman_cosine" in entry or "loss" in entry
    ]
    dev_curve_path = DATA_DIR / "dev_curve.json"
    dev_curve_path.write_text(json.dumps(dev_curve, indent=2) + "\n", encoding="utf-8")

    return {
        "n_mnrl_pairs": len(mnrl_records),
        "n_graded_pairs": len(graded_records),
        "n_dev_scenarios": len(dev_evaluator.sentences1),
        "best_dev_spearman_cosine": trainer.state.best_metric,
        "output_dir": str(OUTPUT_MODEL_DIR),
        "hyperparams": {
            "epochs": NUM_EPOCHS,
            "learning_rate": LEARNING_RATE,
            "batch_size": BATCH_SIZE,
            "warmup_ratio": WARMUP_RATIO,
            "early_stopping_patience": EARLY_STOPPING_PATIENCE,
            "seed": SEED,
        },
    }


if __name__ == "__main__":
    summary = train()
    print(json.dumps(summary, indent=2))
