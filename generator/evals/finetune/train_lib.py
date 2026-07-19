from __future__ import annotations

"""
Configurable SBERT contrastive fine-tuning, shared by train.py (the original
v1/v2 recipe, kept byte-for-byte reproducible) and the method-sweep runners
(spec-hinglish-diagnostic-sweep.md Step 1a-e).

train.py's module-level behavior is preserved exactly (same defaults, same
output paths) by calling run_training() with a TrainConfig built from its own
constants -- this module does not change train.py's reproducibility guarantee
for the already-reported v1/v2 results.

Capacity-control methods (Step 1a):
  full       -- every parameter trainable (the v1/v2 recipe).
  freeze     -- freeze token/position embeddings + the bottom
                `freeze_n_layers` of 12 transformer layers; everything above
                (remaining layers + pooling) trains normally.
  lora       -- wrap encoder self-attention query/value projections with a
                low-rank adapter (peft.LoraConfig); base weights frozen,
                only adapter params + pooling train. Adapter is merged back
                into plain linear weights before saving, so the checkpoint
                loads via a bare `SentenceTransformer(path)` exactly like
                every other config (eval_model.py needs no LoRA-awareness).
  head_only -- the minimal-capacity extreme. The base model's pooling is a
                fixed (parameter-free) mean -- there is no existing learnable
                head to isolate -- so this freezes the ENTIRE transformer and
                appends one new trainable Linear(768, 768) projection after
                pooling (standard SBERT `models.Dense`), matching the spec's
                "train only the pooling/projection head, base frozen
                entirely" with a real (if newly added) projection to train.
"""

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from datasets import Dataset
from sentence_transformers import (
    SentenceTransformer,
    SentenceTransformerTrainer,
    SentenceTransformerTrainingArguments,
    models,
)
from sentence_transformers.evaluation import EmbeddingSimilarityEvaluator
from sentence_transformers.losses import CosineSimilarityLoss, MultipleNegativesRankingLoss
from transformers import EarlyStoppingCallback

from evals.finetune.eval_model import OFF_THE_SHELF_MODEL
from evals.finetune.split import load_split

DATA_DIR = Path(__file__).parent / "data"
SCENARIOS_PATH = Path(__file__).parent.parent / "scenarios" / "dim1_hien.json"
CHECKPOINT_ROOT = Path(__file__).parent / "checkpoints"
RUNS_DIR = Path(__file__).parent / "data" / "runs"

TIER_SCORE = {"near": 0.85, "mid": 0.55, "far": 0.05}

# LoRA targets standard BERT self-attention query/value projections only
# (the original LoRA paper's minimal, most-effective target set) -- not
# key, not the output/intermediate dense layers, to keep the adapter's
# effective capacity genuinely small.
LORA_TARGET_MODULES = ["query", "value"]


@dataclass
class TrainConfig:
    name: str
    method: str = "full"  # "full" | "freeze" | "lora" | "head_only"
    freeze_n_layers: int = 0
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.1
    learning_rate: float = 2e-5
    num_epochs: int = 4
    batch_size: int = 16
    warmup_ratio: float = 0.1
    early_stopping_patience: int = 2
    seed: int = 42
    mnrl_path: Path = field(default_factory=lambda: DATA_DIR / "train_mnrl_pairs.jsonl")
    graded_path: Path = field(default_factory=lambda: DATA_DIR / "train_graded_pairs.jsonl")
    mnrl_records: list[dict] | None = None  # override in-memory (learning-curve subsets)
    graded_records: list[dict] | None = None
    max_steps: int = -1  # -1 = no cap; used only by smoke tests


def _set_all_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _build_dev_evaluator() -> EmbeddingSimilarityEvaluator:
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


def _apply_capacity_control(model: SentenceTransformer, cfg: TrainConfig) -> SentenceTransformer:
    transformer = model[0].auto_model

    if cfg.method == "full":
        return model

    if cfg.method == "freeze":
        for p in transformer.embeddings.parameters():
            p.requires_grad = False
        for i, layer in enumerate(transformer.encoder.layer):
            if i < cfg.freeze_n_layers:
                for p in layer.parameters():
                    p.requires_grad = False
        return model

    if cfg.method == "head_only":
        for p in transformer.parameters():
            p.requires_grad = False
        dense = models.Dense(
            in_features=model.get_embedding_dimension(),
            out_features=model.get_embedding_dimension(),
            activation_function=torch.nn.Identity(),
        )
        modules = list(model._modules.values())
        modules.append(dense)
        return SentenceTransformer(modules=modules)

    if cfg.method == "lora":
        from peft import LoraConfig, get_peft_model

        lora_cfg = LoraConfig(
            r=cfg.lora_r,
            lora_alpha=cfg.lora_alpha,
            lora_dropout=cfg.lora_dropout,
            target_modules=LORA_TARGET_MODULES,
            bias="none",
        )
        # `auto_model` is a read-only property aliasing the real backing
        # attribute `model` (sentence_transformers.base.modules.transformer.
        # Transformer) -- assigning `.auto_model` silently no-ops (nn.Module's
        # __setattr__ stores it under a throwaway `_modules` key without ever
        # calling the property's setter, and there is no setter). Must assign
        # the real attribute `.model` for the wrap to actually take effect.
        model[0].model = get_peft_model(transformer, lora_cfg)
        return model

    raise ValueError(f"unknown capacity-control method: {cfg.method!r}")


def _load_best_lora_checkpoint(
    model: SentenceTransformer,
    trainer: SentenceTransformerTrainer,
    dev_evaluator: EmbeddingSimilarityEvaluator,
) -> None:
    """
    Work around a real bug in transformers.Trainer._load_best_model(): it
    branches on `_is_peft_model(self.model)`, but for
    SentenceTransformerTrainer `self.model` is the OUTER SentenceTransformer
    container, never a PeftModel itself -- the PeftModel lives nested at
    `model[0].auto_model`. `_is_peft_model` therefore returns False, so the
    Trainer's load falls through to its non-PEFT branch, which looks for a
    full `model.safetensors`/`pytorch_model.bin` in the checkpoint dir -- but
    a LoRA checkpoint only ever contains `adapter_model.safetensors`.
    `load_best_model_at_end=True` therefore silently keeps whatever weights
    the LAST epoch left in the live model, never actually restoring the
    tracked-best epoch. Reproduced directly: reloading a saved LoRA
    checkpoint and recomputing its dev score exactly matched the last
    epoch's value, not the best-tracked one (docs/known-limitations.md
    entry 21).

    Fix: explicitly load the best checkpoint's adapter weights into the live
    PeftModel via `peft.set_peft_model_state_dict` (the correct low-level
    restoration API -- bypasses the Trainer's broken auto-detection
    entirely), then verify the reload actually worked by recomputing the dev
    score and asserting it matches the tracked best. Fails loudly, not
    silently, if the checkpoint file is missing or the reload doesn't
    reproduce the tracked score -- this must never again fail silent.
    """
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    best_checkpoint = Path(trainer.state.best_model_checkpoint)
    adapter_path = best_checkpoint / "adapter_model.safetensors"
    if not adapter_path.exists():
        raise RuntimeError(
            f"expected LoRA adapter checkpoint at {adapter_path}, not found -- "
            "cannot restore the trainer's tracked-best checkpoint"
        )

    peft_model = model[0].auto_model
    state_dict = load_file(str(adapter_path))
    set_peft_model_state_dict(peft_model, state_dict)

    reloaded_score = dev_evaluator(model)["dev_spearman_cosine"]
    expected = trainer.state.best_metric
    if abs(reloaded_score - expected) > 1e-4:
        raise RuntimeError(
            f"best-checkpoint reload verification FAILED: recomputed dev "
            f"spearman {reloaded_score:.6f} != trainer's tracked best "
            f"{expected:.6f} (checkpoint {best_checkpoint}) -- the restored "
            "weights do not match what the trainer claims is the best epoch"
        )


def _merge_lora_if_needed(model: SentenceTransformer, cfg: TrainConfig) -> SentenceTransformer:
    if cfg.method != "lora":
        return model
    from peft import PeftModel

    peft_model = model[0].auto_model
    assert isinstance(peft_model, PeftModel), f"expected PeftModel, got {type(peft_model)}"
    model[0].model = peft_model.merge_and_unload()
    return model


def run_training(cfg: TrainConfig) -> dict:
    _set_all_seeds(cfg.seed)

    mnrl_records = cfg.mnrl_records if cfg.mnrl_records is not None else _load_jsonl(cfg.mnrl_path)
    graded_records = (
        cfg.graded_records if cfg.graded_records is not None else _load_jsonl(cfg.graded_path)
    )

    mnrl_dict = {
        "anchor": [r["anchor"] for r in mnrl_records],
        "positive": [r["positive"] for r in mnrl_records],
    }
    if mnrl_records and "negative" in mnrl_records[0]:
        # Mined hard negatives (Step 1b, objective alignment) -- MNRL
        # supports an explicit "negative" column alongside its default
        # in-batch negatives; every record must carry one if any does.
        mnrl_dict["negative"] = [r["negative"] for r in mnrl_records]
    mnrl_ds = Dataset.from_dict(mnrl_dict)
    graded_ds = Dataset.from_dict(
        {
            "sentence1": [r["sentence1"] for r in graded_records],
            "sentence2": [r["sentence2"] for r in graded_records],
            "score": [r["score"] for r in graded_records],
        }
    )

    model = SentenceTransformer(OFF_THE_SHELF_MODEL)
    model = _apply_capacity_control(model, cfg)

    losses = {
        "mnrl": MultipleNegativesRankingLoss(model),
        "graded": CosineSimilarityLoss(model),
    }
    train_dataset = {"mnrl": mnrl_ds, "graded": graded_ds}

    dev_evaluator = _build_dev_evaluator()

    output_dir = CHECKPOINT_ROOT / cfg.name
    args_kwargs = dict(
        output_dir=str(output_dir),
        num_train_epochs=cfg.num_epochs,
        per_device_train_batch_size=cfg.batch_size,
        per_device_eval_batch_size=cfg.batch_size,
        learning_rate=cfg.learning_rate,
        warmup_ratio=cfg.warmup_ratio,
        seed=cfg.seed,
        data_seed=cfg.seed,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_dev_spearman_cosine",
        greater_is_better=True,
        logging_steps=10,
        report_to=[],
    )
    if cfg.max_steps > 0:
        args_kwargs["max_steps"] = cfg.max_steps
        args_kwargs["save_strategy"] = "no"
        args_kwargs["eval_strategy"] = "no"
        args_kwargs["load_best_model_at_end"] = False
    args = SentenceTransformerTrainingArguments(**args_kwargs)

    callbacks = (
        []
        if cfg.max_steps > 0
        else [EarlyStoppingCallback(early_stopping_patience=cfg.early_stopping_patience)]
    )
    trainer = SentenceTransformerTrainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        loss=losses,
        evaluator=None if cfg.max_steps > 0 else dev_evaluator,
        callbacks=callbacks,
    )
    trainer.train()

    if cfg.method == "lora" and trainer.state.best_model_checkpoint is not None:
        _load_best_lora_checkpoint(model, trainer, dev_evaluator)

    # Snapshot trainable/total param counts BEFORE the LoRA merge -- merging
    # folds adapter weights into plain frozen Linear layers and zeroes out
    # requires_grad everywhere, which would misreport a LoRA run as having
    # trained 0 parameters.
    n_trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    n_total = sum(p.numel() for p in model.parameters())

    model = _merge_lora_if_needed(model, cfg)

    model_dir = output_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    model.save(str(model_dir))

    _dev_curve_keys = ("epoch", "step", "eval_dev_spearman_cosine", "loss")
    dev_curve = [
        {k: v for k, v in entry.items() if k in _dev_curve_keys}
        for entry in trainer.state.log_history
        if "eval_dev_spearman_cosine" in entry or "loss" in entry
    ]

    summary = {
        "name": cfg.name,
        "method": cfg.method,
        "n_mnrl_pairs": len(mnrl_records),
        "n_graded_pairs": len(graded_records),
        "n_dev_scenarios": len(dev_evaluator.sentences1),
        "best_dev_spearman_cosine": trainer.state.best_metric,
        "dev_curve": dev_curve,
        "n_trainable_params": n_trainable,
        "n_total_params": n_total,
        "trainable_fraction": n_trainable / n_total if n_total else None,
        "output_dir": str(model_dir),
        "hyperparams": {
            "method": cfg.method,
            "freeze_n_layers": cfg.freeze_n_layers,
            "lora_r": cfg.lora_r,
            "lora_alpha": cfg.lora_alpha,
            "learning_rate": cfg.learning_rate,
            "num_epochs": cfg.num_epochs,
            "batch_size": cfg.batch_size,
            "warmup_ratio": cfg.warmup_ratio,
            "early_stopping_patience": cfg.early_stopping_patience,
            "seed": cfg.seed,
        },
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{cfg.name}.train_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary
