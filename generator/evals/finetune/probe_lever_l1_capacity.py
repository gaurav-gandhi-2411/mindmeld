from __future__ import annotations

"""
Cheap probe: does HIGHER LoRA CAPACITY (rank and/or target-module coverage)
move the needle on the "subword-tokenization-collision" residual documented
in docs/known-limitations.md entry 20 (junoon/registan/jheel/udaasi -- their
romanized spelling fragments into subword pieces that coincidentally match
unrelated English morphemes, corrupting the embedding at the input level)?

This is a DIFFERENT lever from probe_subword_collision.py's "more hard
negatives at the SAME LoRA rank r=8" (PROVEN DEAD -- full-34 dim1 delta
+0.0037 not significant, dim2 delta -0.0606 not significant/directionally
negative). The r=8 config was chosen for the original 1741-pair data regime
and never re-swept at higher rank / more target modules against this
specific residual. Hypothesis: the collision may need more representational
room to route around bad tokenization.

Isolation from probe_subword_collision.py's confound: NO new word-specific
training pairs are added here. Training data is the EXACT SAME files the
shipped model's winning "obj_hard_neg" recipe trained on --
train_mnrl_pairs_hard_neg.jsonl + train_graded_pairs.jsonl -- loaded AS-IS,
unmodified, unextended. Only the LoRA capacity knobs (r, target_modules)
vary across the 4 sweep configs; every other hyperparameter is held fixed
at the shipped obj_hard_neg recipe's values (learning_rate=2e-4, epochs=4,
early_stopping_patience=2, batch_size=16, warmup_ratio=0.1, seed=42; alpha
follows the shipped recipe's r=8/alpha=16 ratio, i.e. alpha=2*r, since that
ratio -- not a fixed alpha -- is what the shipped recipe actually used).

Sweep (all method="lora"):
  cap_r16          -- r=16,  alpha=32,  target_modules=[query, value] (default)
  cap_r32          -- r=32,  alpha=64,  target_modules=[query, value] (default)
  cap_r64          -- r=64,  alpha=128, target_modules=[query, value] (default)
  cap_r16_expanded -- r=16,  alpha=32,  target_modules=[query, value, key, dense]

target_modules for cap_r16_expanded verified by direct introspection of
l3cube-pune/indic-sentence-bert-nli's named_modules() (a standard BERT
encoder): each transformer layer exposes attention.self.{query,key,value}
(3 separate Linear projections) and attention.output.dense +
intermediate.dense + output.dense (3 more Linear layers, all matched by the
single substring "dense" since PEFT's target_modules match is a
suffix/name match applied per-module, not a single shared layer -- "dense"
correctly hits all 3 distinct FFN/attention-output Linear layers in every
encoder layer, which is the intended "additional attention/FFN linear
layer" coverage, not a bug). "key" adds the attention key projection.
Nothing here targets embeddings or the pooling layer.

Evaluates each trained checkpoint on the frozen public 34-secret benchmark
(data/public_benchmark_staging/dim1_hien.json + dim2_pairs.json), paired
against the shipped model's already-computed bakeoff_raw checkpoint (no
re-embedding of the shipped model) -- reusing probe_subword_collision.py's
exact scoring/comparator machinery (_public_benchmark_dim1_records,
_public_benchmark_dim2_result, _shipped_model_dim1_records_34,
_shipped_model_dim2_records_34, _target_word_summary) rather than
duplicating it.

Run (from generator/):
    uv run python -m evals.finetune.probe_lever_l1_capacity --train
    uv run python -m evals.finetune.probe_lever_l1_capacity --eval
"""

import argparse
import json
import time
from pathlib import Path

from evals.finetune.bootstrap_ci import (
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.probe_subword_collision import (
    PUBLIC_BENCHMARK_34_SECRETS,  # noqa: F401  (re-exported for callers/tests)
    TARGET_WORDS,
    _public_benchmark_dim1_records,
    _public_benchmark_dim2_result,
    _shipped_model_dim1_records_34,
    _shipped_model_dim2_records_34,
    _target_word_summary,
)
from evals.finetune.train_lib import DATA_DIR, TrainConfig, run_training
from evals.harness.dimension1_ranking import _band_accuracy

RUN_NAME = "probe_lever_l1_capacity"

# The 4 capacity configs under test. alpha = 2*r everywhere, matching the
# shipped obj_hard_neg recipe's own r=8/alpha=16 ratio (not a fixed alpha --
# see module docstring). target_modules=None means "use train_lib's
# LORA_TARGET_MODULES default ([query, value])", exactly the shipped recipe.
SWEEP_CONFIGS: list[dict] = [
    {"config_name": "cap_r16", "lora_r": 16, "lora_alpha": 32, "lora_target_modules": None},
    {"config_name": "cap_r32", "lora_r": 32, "lora_alpha": 64, "lora_target_modules": None},
    {"config_name": "cap_r64", "lora_r": 64, "lora_alpha": 128, "lora_target_modules": None},
    {
        "config_name": "cap_r16_expanded",
        "lora_r": 16,
        "lora_alpha": 32,
        "lora_target_modules": ["query", "value", "key", "dense"],
    },
]


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def load_base_training_set() -> tuple[list[dict], list[dict]]:
    """The obj_hard_neg base training set (train_mnrl_pairs_hard_neg.jsonl +
    train_graded_pairs.jsonl -- the exact files the SHIPPED model trained
    on), loaded AS-IS with no extra records appended. This isolates the
    capacity variable cleanly -- no data confound with probe_subword_
    collision.py's second-round hard-negative-mining probe."""
    mnrl = _load_jsonl(DATA_DIR / "train_mnrl_pairs_hard_neg.jsonl")
    graded = _load_jsonl(DATA_DIR / "train_graded_pairs.jsonl")
    return mnrl, graded


# ---------------------------------------------------------------------------
# Train: one LoRA run per sweep config, same recipe as shipped obj_hard_neg
# otherwise (learning_rate=2e-4, num_epochs=4, early_stopping_patience=2,
# batch_size=16, warmup_ratio=0.1, seed=42 -- all TrainConfig defaults that
# already match, per data/runs/obj_hard_neg.train_summary.json's
# "hyperparams" block).
# ---------------------------------------------------------------------------


def train_all_configs() -> dict[str, dict]:
    mnrl_records, graded_records = load_base_training_set()
    print(f"base training set (unmodified, no-leakage-inherited): {len(mnrl_records)} mnrl, "
          f"{len(graded_records)} graded")

    summaries: dict[str, dict] = {}
    for sweep_cfg in SWEEP_CONFIGS:
        name = sweep_cfg["config_name"]
        cfg = TrainConfig(
            name=f"{RUN_NAME}_{name}",
            method="lora",
            lora_r=sweep_cfg["lora_r"],
            lora_alpha=sweep_cfg["lora_alpha"],
            lora_target_modules=sweep_cfg["lora_target_modules"],
            learning_rate=2e-4,
            num_epochs=4,
            early_stopping_patience=2,
            mnrl_records=mnrl_records,
            graded_records=graded_records,
        )
        print(f"--- training {name} (r={cfg.lora_r}, alpha={cfg.lora_alpha}, "
              f"target_modules={cfg.lora_target_modules}) ---")
        t0 = time.monotonic()
        summary = run_training(cfg)
        elapsed = time.monotonic() - t0
        summary["_wall_clock_s"] = elapsed
        print(f"--- {name} done in {elapsed:.1f}s, best_dev_spearman_cosine="
              f"{summary['best_dev_spearman_cosine']:.4f} ---")
        summaries[name] = summary
    return summaries


# ---------------------------------------------------------------------------
# Evaluate: reuses probe_subword_collision.py's scoring/comparator machinery
# verbatim (imported above), applied per sweep config.
# ---------------------------------------------------------------------------


def evaluate_config(config_name: str, model_path: str, lora_r: int, lora_target_modules: list) -> dict:
    """Full evaluation for ONE trained capacity-sweep checkpoint: probe
    model's dim1/dim2 on the public 34-secret benchmark, paired bootstrap
    deltas vs the shipped model, target-word-specific before/after, and a
    regression-floor check -- identical shape/logic to probe_subword_
    collision.py's evaluate_probe(), applied once per sweep config."""
    probe_dim1 = _public_benchmark_dim1_records(model_path)
    probe_dim2 = _public_benchmark_dim2_result(model_path)

    shipped_dim1 = _shipped_model_dim1_records_34()
    shipped_dim2 = _shipped_model_dim2_records_34()

    probe_dim1_ci = bootstrap_dim1_spearman_ci(probe_dim1)
    probe_dim2_ci = bootstrap_dim2_pass_rate_ci(probe_dim2["records"])
    shipped_dim1_ci = bootstrap_dim1_spearman_ci(shipped_dim1)
    shipped_dim2_ci = bootstrap_dim2_pass_rate_ci(shipped_dim2)

    dim1_delta = paired_bootstrap_dim1_delta(shipped_dim1, probe_dim1)
    dim2_delta = paired_bootstrap_dim2_delta(shipped_dim2, probe_dim2["records"])

    by_tier = {t: [r for r in probe_dim1 if r["tier"] == t] for t in ("near", "mid", "far")}
    probe_band_accuracy = {
        "overall": _band_accuracy(probe_dim1),
        "near": _band_accuracy(by_tier["near"]),
        "mid": _band_accuracy(by_tier["mid"]),
        "far": _band_accuracy(by_tier["far"]),
    }

    shipped_pass = {r["hien_secret"]: r["consistent"] for r in shipped_dim2}
    probe_pass = {r["hien_secret"]: r["consistent"] for r in probe_dim2["records"]}
    common_secrets = sorted(set(shipped_pass) & set(probe_pass))
    newly_broken = [
        s for s in common_secrets if shipped_pass[s] is True and probe_pass[s] is not True
    ]
    newly_fixed = [
        s for s in common_secrets if shipped_pass[s] is not True and probe_pass[s] is True
    ]

    target_before = _target_word_summary(shipped_dim1, shipped_dim2)
    target_after = _target_word_summary(probe_dim1, probe_dim2["records"])

    return {
        "config_name": config_name,
        "lora_r": lora_r,
        "lora_target_modules": lora_target_modules,
        "model_path": model_path,
        "n_dim1_secrets": len({r["secret"] for r in probe_dim1}),
        "n_dim1_scenarios": len(probe_dim1),
        "n_dim2_pairs": len(probe_dim2["records"]),
        "probe_dim1_spearman_ci": probe_dim1_ci,
        "probe_dim2_pass_rate_ci": probe_dim2_ci,
        "shipped_dim1_spearman_ci": shipped_dim1_ci,
        "shipped_dim2_pass_rate_ci": shipped_dim2_ci,
        "probe_band_accuracy": probe_band_accuracy,
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim2_regression_floor": {
            "n_common_secrets": len(common_secrets),
            "n_newly_broken": len(newly_broken),
            "newly_broken": newly_broken,
            "n_newly_fixed": len(newly_fixed),
            "newly_fixed": newly_fixed,
        },
        "target_words_before_shipped": target_before,
        "target_words_after_probe": target_after,
    }


def evaluate_all_configs(train_summaries: dict[str, dict] | None = None) -> dict[str, dict]:
    """Evaluate every sweep config's trained checkpoint. If train_summaries
    is not given (e.g. running --eval after a separate --train invocation),
    resolves each config's output_dir from its own persisted
    data/runs/{RUN_NAME}_{config_name}.train_summary.json, same convention
    probe_subword_collision.evaluate_probe() uses."""
    results: dict[str, dict] = {}
    for sweep_cfg in SWEEP_CONFIGS:
        name = sweep_cfg["config_name"]
        if train_summaries is not None and name in train_summaries:
            model_path = train_summaries[name]["output_dir"]
        else:
            summary_path = DATA_DIR / "runs" / f"{RUN_NAME}_{name}.train_summary.json"
            model_path = json.loads(summary_path.read_text(encoding="utf-8"))["output_dir"]

        print(f"--- evaluating {name} ({model_path}) ---")
        results[name] = evaluate_config(
            config_name=name,
            model_path=model_path,
            lora_r=sweep_cfg["lora_r"],
            lora_target_modules=sweep_cfg["lora_target_modules"],
        )

    out_path = DATA_DIR / f"{RUN_NAME}.eval_result.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true", help="run all 4 capacity-sweep fine-tunes")
    parser.add_argument("--eval", action="store_true", help="evaluate all 4 trained checkpoints")
    args = parser.parse_args()

    train_summaries: dict[str, dict] | None = None
    if args.train:
        train_summaries = train_all_configs()
    if args.eval or not (args.train or args.eval):
        evaluate_all_configs(train_summaries)


if __name__ == "__main__":
    main()
