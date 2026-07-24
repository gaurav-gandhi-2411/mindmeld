from __future__ import annotations

"""
Variant-augmented contrastive retraining candidate (spec-model-excellence.md
WORKSTREAM C, item 10) -- gated attempt at closing the spelling-invariance
gap spelling_robustness.py just measured (aksharantar_heldout band-agreement
rate 67.4% [0.538, 0.801] on 267 genuinely held-out real-world spelling
variants, verdict "NOT SUPPORTED").

Recipe: EXACT SAME as the shipped model (obj_hard_neg -- LoRA r=8, lr=2e-4,
4 epochs, mined hard negatives; step1b_objective_sweep.py's WINNER_KWARGS),
data-only change. The variant-augmented MNRL/graded files
(assemble_data.build(variant_augmented=True) -- new Aksharantar-mined
spelling-variant pairs layered ADDITIVELY on top of the 5 production
sources, never replacing them) are hard-negative-mined the same way
(hard_negatives.py) and trained via train_lib.run_training with an
otherwise byte-identical TrainConfig.

Hard-negative reference model: forced to eval_model.OFF_THE_SHELF_MODEL
explicitly, NOT whatever config.MODELS["hi-en"] currently is -- production
config now points at the SHIPPED fine-tune (config.py, commit 9d82165),
but git history confirms the ORIGINAL train_mnrl_pairs_hard_neg.jsonl was
mined while config.MODELS["hi-en"] still pointed at the off-the-shelf
reference (l3cube-pune/indic-sentence-bert-nli) -- both the mining run and
the config flip landed in the same ship commit, mining first. Reusing
today's config.MODELS default would silently swap the "hard negative"
reference model out from under the recipe.

STAGING ONLY: writes the new checkpoint to
evals/finetune/checkpoints/variant_augmented/model -- NEVER touches
checkpoints/obj_hard_neg/model (the shipped checkpoint) or evals/finetune/
model/ (the currently-published model files). Never pushes to HuggingFace;
promotion is a human (GG) decision, per every other production-facing
change in this program.

Gate (Step 3, spec-mandated "full suite, zero net regression"): dim1/dim2
regression floors (regression.py, zero-broken-pairs) + paired-bootstrap
deltas (dim1 Spearman, dim2 pass-rate, every topheavy submetric, top-
weighted correlation, band ECE) -- candidate vs the CURRENTLY SHIPPED
model, on the same 42-secret/379-scenario combined test set
benchmark_bakeoff.py uses.

Success criterion (Step 4): does the candidate's aksharantar_heldout
band-agreement rate improve, with a CI-meaningful (not just point-estimate)
delta, over the shipped baseline's 67.4% [0.538, 0.801]? spelling_
robustness.build_report(model_override=...) recomputes BOTH canonical and
variant ranks fresh under the candidate -- never mixes candidate variant
ranks against the shipped model's canonical ranks (see that function's
updated docstring).

Run (from generator/, GPU strongly recommended -- RTX 3070 8GB confirmed
available in this environment):
    uv run python -m evals.finetune.probe_variant_augmented_retrain
"""

import json
import time
from pathlib import Path

import numpy as np

from evals.finetune import assemble_data
from evals.finetune.benchmark_bakeoff import evaluate_one_model
from evals.finetune.bootstrap_ci import (
    _TIER_ORDINAL,
    N_BOOT,
    SEED,
    _dim1_by_secret,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import OFF_THE_SHELF_MODEL, _model_override
from evals.finetune.hard_negatives import mine_hard_negatives
from evals.finetune.probe_l2_collision_scan_extension import paired_bootstrap_topheavy_delta
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from evals.finetune.spelling_robustness import build_report as spelling_build_report
from evals.finetune.split import load_split
from evals.finetune.train_lib import TrainConfig, run_training
from evals.harness import topheavy
from evals.harness.metrics import top_weighted_correlation
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
BAKEOFF_RAW_DIR = DATA_DIR / "bakeoff_raw"

SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"
SHIPPED_CHECKPOINT_PATH = BAKEOFF_RAW_DIR / "gauravgandhi2411__hinglish-relatedness-sbert.json"
BASELINE_SPELLING_REPORT_PATH = DATA_DIR / "spelling_robustness_report.json"

CANDIDATE_NAME = "variant_augmented"
CANDIDATE_MNRL_PATH = DATA_DIR / "train_mnrl_pairs_variant_augmented.jsonl"
CANDIDATE_GRADED_PATH = DATA_DIR / "train_graded_pairs_variant_augmented.jsonl"
CANDIDATE_MNRL_HARD_NEG_PATH = DATA_DIR / "train_mnrl_pairs_hard_neg_variant_augmented.jsonl"
CANDIDATE_CHECKPOINT_MODEL_DIR = Path(__file__).parent / "checkpoints" / CANDIDATE_NAME / "model"

# step1b_objective_sweep.py WINNER_KWARGS -- the shipped obj_hard_neg recipe,
# reproduced verbatim (every other TrainConfig field left at its dataclass
# default, exactly as the original sweep did).
SHIPPED_RECIPE_KWARGS: dict = {
    "method": "lora",
    "lora_r": 8,
    "learning_rate": 2e-4,
    "num_epochs": 4,
    "early_stopping_patience": 2,
}

REPORT_JSON_PATH = DATA_DIR / "probe_variant_augmented_retrain.eval_result.json"
REPORT_MD_PATH = DATA_DIR / "probe_variant_augmented_retrain.report.md"


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ---------------------------------------------------------------------------
# Step 1: assemble + verify the variant-augmented training data.
# ---------------------------------------------------------------------------


def step1_assemble_and_verify() -> dict:
    """Builds train_mnrl_pairs_variant_augmented.jsonl (via
    assemble_data.build(variant_augmented=True) -- the production
    train_mnrl_pairs.jsonl/train_graded_pairs.jsonl stay byte-identical,
    never written to by this path), then re-verifies (a) the built-in
    _assert_no_leakage already ran inside build() and (b) zero WORD-level
    overlap between the new variant pairs and the 267-record
    aksharantar_heldout eval set (spec's explicit "coincidental overlap"
    concern -- an eval variant spelling could in principle also appear as a
    training pair for a DIFFERENT word)."""
    counts = assemble_data.build(variant_augmented=True)

    mnrl = _load_jsonl(CANDIDATE_MNRL_PATH)
    variant_mnrl = [r for r in mnrl if r["source"] == "variant"]

    baseline_spelling = json.loads(BASELINE_SPELLING_REPORT_PATH.read_text(encoding="utf-8"))
    eval_records = [
        r for r in baseline_spelling["all_drift_records"] if r["category"] == "aksharantar_heldout"
    ]
    eval_touched_words: set[str] = set()
    for r in eval_records:
        eval_touched_words.add(r["secret"].lower())
        eval_touched_words.add(r["word"].lower())
        eval_touched_words.add(r["variant_word"].lower())

    collisions = [
        r
        for r in variant_mnrl
        if r["anchor"].lower() in eval_touched_words or r["positive"].lower() in eval_touched_words
    ]

    return {
        "counts": counts,
        "n_variant_mnrl_pairs_final": len(variant_mnrl),
        "n_eval_touched_words_267_set": len(eval_touched_words),
        "n_eval_drift_records": len(eval_records),
        "n_collisions_with_267_eval_set": len(collisions),
        "collisions": collisions,
        "zero_collision_verdict": len(collisions) == 0,
    }


# ---------------------------------------------------------------------------
# Step 2: hard-negative mining + LoRA training, byte-identical recipe.
# ---------------------------------------------------------------------------


TRAIN_SUMMARY_PATH = DATA_DIR / "runs" / f"{CANDIDATE_NAME}.train_summary.json"


def step2_mine_and_train(*, reuse_existing_checkpoint: bool = False) -> dict:
    """`reuse_existing_checkpoint=True` skips hard-negative mining + training
    entirely and reloads the already-persisted train_summary.json -- LoRA
    training is deterministic (seed=42) and CPU wall-clock-expensive
    (~6 minutes for this dataset size), so re-running it after an unrelated
    downstream bug fix (e.g. Step 4) wastes ~6 minutes reproducing a
    checkpoint that is already on disk and already verified against its own
    tracked-best dev score (train_lib._load_best_lora_checkpoint's built-in
    reload-verification assertion, which already passed once this run)."""
    if reuse_existing_checkpoint:
        if not (CANDIDATE_CHECKPOINT_MODEL_DIR / "model.safetensors").exists():
            raise RuntimeError(
                f"reuse_existing_checkpoint=True but {CANDIDATE_CHECKPOINT_MODEL_DIR} has no "
                "model.safetensors -- run without this flag first"
            )
        train_summary = json.loads(TRAIN_SUMMARY_PATH.read_text(encoding="utf-8"))
        mine_stats = None
        if CANDIDATE_MNRL_HARD_NEG_PATH.exists():
            mine_stats = {"reused_from_disk": str(CANDIDATE_MNRL_HARD_NEG_PATH)}
        return {
            "hard_neg_mining_stats": mine_stats,
            "train_summary": train_summary,
            "wall_clock_seconds": None,
            "checkpoint_dir": str(CANDIDATE_CHECKPOINT_MODEL_DIR),
            "reused_existing_checkpoint": True,
        }

    with _model_override(OFF_THE_SHELF_MODEL):
        mine_stats = mine_hard_negatives(CANDIDATE_MNRL_PATH, CANDIDATE_MNRL_HARD_NEG_PATH)

    hard_neg_records = _load_jsonl(CANDIDATE_MNRL_HARD_NEG_PATH)
    graded_records = _load_jsonl(CANDIDATE_GRADED_PATH)

    cfg = TrainConfig(
        name=CANDIDATE_NAME,
        mnrl_records=hard_neg_records,
        graded_records=graded_records,
        **SHIPPED_RECIPE_KWARGS,
    )
    t0 = time.monotonic()
    train_summary = run_training(cfg)
    wall_clock_seconds = round(time.monotonic() - t0, 1)

    return {
        "hard_neg_mining_stats": mine_stats,
        "train_summary": train_summary,
        "wall_clock_seconds": wall_clock_seconds,
        "checkpoint_dir": str(CANDIDATE_CHECKPOINT_MODEL_DIR),
        "reused_existing_checkpoint": False,
    }


# ---------------------------------------------------------------------------
# Step 3: gate on the full Workstream A suite vs the SHIPPED model. Two
# paired-delta helpers not already in bootstrap_ci.py (top_weighted_
# correlation, band ECE) are added HERE, mirroring paired_bootstrap_
# dim1_delta's exact resample-once-apply-to-both pattern, same precedent as
# probe_l2_collision_scan_extension.py adding paired_bootstrap_topheavy_delta
# locally rather than modifying bootstrap_ci.py.
# ---------------------------------------------------------------------------


def _paired_bootstrap_twc_delta(
    baseline_records: list[dict],
    candidate_records: list[dict],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    """Paired cluster-bootstrap (by secret) delta CI on pooled
    top_weighted_correlation(expected_ordinal, actual_rank) -- mirrors
    bootstrap_ci.bootstrap_top_weighted_correlation_ci's point-estimate
    computation, generalized to a paired baseline-vs-candidate delta the
    same way paired_bootstrap_dim1_delta generalizes bootstrap_dim1_
    spearman_ci."""

    def _twc_for(by_secret: dict, secrets: list[str]) -> float:
        recs = [r for s in secrets for r in by_secret[s]]
        expected = [_TIER_ORDINAL[r["tier"]] for r in recs]
        actual = [r["actual_rank"] for r in recs]
        return top_weighted_correlation(expected, actual)

    base_by_secret = _dim1_by_secret(baseline_records)
    cand_by_secret = _dim1_by_secret(candidate_records)
    secrets = sorted(set(base_by_secret) & set(cand_by_secret))
    base_point = _twc_for(base_by_secret, secrets)
    cand_point = _twc_for(cand_by_secret, secrets)
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        b = _twc_for(base_by_secret, resample)
        c = _twc_for(cand_by_secret, resample)
        if not (np.isnan(b) or np.isnan(c)):
            deltas.append(c - b)
    lo, hi = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    return {
        "baseline_point": base_point,
        "candidate_point": cand_point,
        "delta_point": cand_point - base_point,
        "delta_ci_95": [lo, hi],
        "ci_significant_improvement": lo > 0,
        "ci_significant_regression": hi < 0,
        "n_clusters": len(secrets),
        "n_valid_bootstrap_draws": len(deltas),
    }


def _paired_bootstrap_band_ece_delta(
    baseline_records: list[dict],
    candidate_records: list[dict],
    vocab_size: int,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    """Paired cluster-bootstrap (by secret) delta CI on
    topheavy.band_calibration_error(...)['ece']. ECE is a LOWER-is-better
    metric, unlike every other submetric in this suite -- "improvement"
    means the candidate-minus-baseline delta's CI sits entirely BELOW zero
    (candidate ECE consistently lower), and "regression" means entirely
    ABOVE zero; the sign convention is deliberately flipped vs every other
    _paired_bootstrap_*_delta helper here, documented explicitly to avoid a
    silent sign-flip bug when this gets read alongside the others."""

    def _ece_for(by_secret: dict, secret_list: list[str]) -> float | None:
        flat = [r for s in secret_list for r in by_secret[s]]
        return topheavy.band_calibration_error(flat, vocab_size)["ece"]

    base_by_secret = _dim1_by_secret(baseline_records)
    cand_by_secret = _dim1_by_secret(candidate_records)
    secrets = sorted(set(base_by_secret) & set(cand_by_secret))
    base_point = _ece_for(base_by_secret, secrets)
    cand_point = _ece_for(cand_by_secret, secrets)
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        b = _ece_for(base_by_secret, resample)
        c = _ece_for(cand_by_secret, resample)
        if b is not None and c is not None:
            deltas.append(c - b)
    if len(deltas) >= 2:
        lo, hi = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    else:
        lo = hi = None
    delta_point = (
        (cand_point - base_point) if (base_point is not None and cand_point is not None) else None
    )
    return {
        "baseline_point": base_point,
        "candidate_point": cand_point,
        "delta_point": delta_point,
        "delta_ci_95": [lo, hi] if lo is not None else None,
        "ci_significant_improvement": (hi is not None and hi < 0),
        "ci_significant_regression": (lo is not None and lo > 0),
        "n_clusters": len(secrets),
        "n_valid_bootstrap_draws": len(deltas),
    }


def _no_topheavy_regression(topheavy_delta: dict) -> bool:
    for metric in ("ndcg", "recall", "precision"):
        for k in topheavy.K_VALUES:
            if topheavy_delta[metric][k].get("ci_significant_regression"):
                return False
    return not topheavy_delta["mrr"].get("ci_significant_regression", False)


def step3_gate_vs_shipped() -> dict:
    split = load_split()
    test_secrets = set(split["test_secrets"])
    vocab_size = len(load_hien_vocab())

    shipped = json.loads(SHIPPED_CHECKPOINT_PATH.read_text(encoding="utf-8"))
    candidate = evaluate_one_model(str(CANDIDATE_CHECKPOINT_MODEL_DIR), test_secrets, vocab_size)

    dim1_floor = dim1_regression_floor(shipped["dim1_records"], candidate["dim1_records"])
    dim2_floor = dim2_regression_floor(shipped["dim2_records"], candidate["dim2_records"])
    topheavy_delta = paired_bootstrap_topheavy_delta(
        shipped["dim1_records"], candidate["dim1_records"]
    )
    dim1_delta = paired_bootstrap_dim1_delta(shipped["dim1_records"], candidate["dim1_records"])
    dim2_delta = paired_bootstrap_dim2_delta(shipped["dim2_records"], candidate["dim2_records"])
    twc_delta = _paired_bootstrap_twc_delta(shipped["dim1_records"], candidate["dim1_records"])
    band_ece_delta = _paired_bootstrap_band_ece_delta(
        shipped["dim1_records"], candidate["dim1_records"], vocab_size
    )

    zero_net_regression = (
        dim1_floor["zero_regression_strict"]
        and dim2_floor["zero_regression_strict"]
        and _no_topheavy_regression(topheavy_delta)
        and not dim1_delta.get("ci_significant_regression", False)
        and not dim2_delta.get("ci_significant_regression", False)
        and not twc_delta.get("ci_significant_regression", False)
        and not band_ece_delta.get("ci_significant_regression", False)
    )

    return {
        "candidate_model_path": str(CANDIDATE_CHECKPOINT_MODEL_DIR),
        "shipped_model": SHIPPED_MODEL,
        "dim1_regression_floor": dim1_floor,
        "dim2_regression_floor": dim2_floor,
        "dim1_spearman_paired_delta": dim1_delta,
        "dim2_pass_rate_paired_delta": dim2_delta,
        "topheavy_paired_delta": topheavy_delta,
        "top_weighted_correlation_paired_delta": twc_delta,
        "band_ece_paired_delta": band_ece_delta,
        "zero_net_regression_verdict": zero_net_regression,
    }


# ---------------------------------------------------------------------------
# Step 4: THE success criterion -- spelling-variance robustness delta.
# ---------------------------------------------------------------------------


def step4_spelling_robustness_delta() -> dict:
    baseline = json.loads(BASELINE_SPELLING_REPORT_PATH.read_text(encoding="utf-8"))
    baseline_aksh = baseline["summary"]["aksharantar_heldout"]["drift"]

    _md, candidate_report = spelling_build_report(
        include_llm=False, model_override=str(CANDIDATE_CHECKPOINT_MODEL_DIR)
    )
    candidate_aksh = candidate_report["summary"]["aksharantar_heldout"]["drift"]

    baseline_agree = baseline_aksh["band_agreement_rate"]["point"]
    candidate_agree = candidate_aksh["band_agreement_rate"]["point"]
    delta_point = (
        (candidate_agree - baseline_agree)
        if (baseline_agree is not None and candidate_agree is not None)
        else None
    )

    baseline_worst = baseline_aksh["worst_case"]
    candidate_same_triple = None
    if baseline_worst is not None:
        for r in candidate_report["all_drift_records"]:
            if (
                r["category"] == "aksharantar_heldout"
                and r["secret"] == baseline_worst["secret"]
                and r["word"] == baseline_worst["word"]
                and r["variant_word"] == baseline_worst["variant_word"]
            ):
                candidate_same_triple = r
                break

    return {
        "baseline_n": baseline_aksh["n"],
        "candidate_n": candidate_aksh["n"],
        "n_matches_verified": baseline_aksh["n"] == candidate_aksh["n"],
        "baseline_band_agreement_rate": baseline_aksh["band_agreement_rate"],
        "candidate_band_agreement_rate": candidate_aksh["band_agreement_rate"],
        "delta_point": delta_point,
        "baseline_mean_rank_drift": baseline_aksh["mean_rank_drift"],
        "candidate_mean_rank_drift": candidate_aksh["mean_rank_drift"],
        "baseline_median_rank_drift": baseline_aksh["median_rank_drift"],
        "candidate_median_rank_drift": candidate_aksh["median_rank_drift"],
        "worst_case_azaadi_rights_specific_comparison": {
            "baseline_worst_case": baseline_worst,
            "candidate_same_triple": candidate_same_triple,
        },
        "candidate_worst_case_overall": candidate_aksh["worst_case"],
        "candidate_report_full": candidate_report,
    }


# ---------------------------------------------------------------------------
# Verdict + reporting.
# ---------------------------------------------------------------------------


def _ci_meaningful_improvement(
    delta_point: float | None, baseline_ci: dict, candidate_ci: dict
) -> bool:
    """A CI-meaningful (not just point-estimate) improvement: the
    candidate's own CI lower bound clears the baseline's point estimate, AND
    the delta itself is positive -- a conservative, honest bar (does NOT
    require the two CIs to be fully non-overlapping, which paired-bootstrap
    delta_ci_95 answers more precisely when available, but this module's
    step4 computes baseline/candidate as two INDEPENDENT bootstrap CIs, not
    a paired delta, since the 267 records span 13 secrets each embedded
    under a DIFFERENT model -- not a valid paired-cluster resample target
    the way Step 3's same-model-family comparisons are)."""
    if delta_point is None or delta_point <= 0:
        return False
    cand_lo = candidate_ci["ci_95"][0] if candidate_ci["ci_95"] is not None else None
    base_point = baseline_ci["point"]
    if cand_lo is None or base_point is None:
        return False
    return cand_lo > base_point


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse-existing-checkpoint",
        action="store_true",
        help="Skip Step 2 (hard-negative mining + LoRA training) and reload the "
        "already-persisted checkpoint/train_summary.json -- for re-running Steps 3/4 "
        "after a downstream fix without repeating the ~6-minute training run.",
    )
    args = parser.parse_args()

    print("=== Step 1: assemble + verify variant-augmented training data ===")
    step1 = step1_assemble_and_verify()
    print(
        f"variant mnrl pairs (final, deduped): {step1['n_variant_mnrl_pairs_final']}; "
        f"collisions with 267-record eval set: {step1['n_collisions_with_267_eval_set']} "
        f"(verdict zero_collision={step1['zero_collision_verdict']})"
    )
    if not step1["zero_collision_verdict"]:
        raise RuntimeError(
            f"eval-set collision detected -- {step1['collisions']} -- refusing to train on "
            "data that overlaps the held-out spelling-robustness eval set"
        )

    print("\n=== Step 2: hard-negative mining + LoRA training ===")
    step2 = step2_mine_and_train(reuse_existing_checkpoint=args.reuse_existing_checkpoint)
    print(
        f"trained in {step2['wall_clock_seconds']}s, "
        f"n_mnrl={step2['train_summary']['n_mnrl_pairs']}, "
        f"n_graded={step2['train_summary']['n_graded_pairs']}, "
        f"best_dev_spearman_cosine (DIAGNOSTIC ONLY, not a result)="
        f"{step2['train_summary']['best_dev_spearman_cosine']}"
    )

    print("\n=== Step 3: gate vs shipped model on full Workstream A suite ===")
    step3 = step3_gate_vs_shipped()
    print(
        f"dim1 floor: fixed={step3['dim1_regression_floor']['n_fixed']} "
        f"broken={step3['dim1_regression_floor']['n_broken']}; "
        f"dim2 floor: fixed={step3['dim2_regression_floor']['n_fixed']} "
        f"broken={step3['dim2_regression_floor']['n_broken']}; "
        f"zero_net_regression_verdict={step3['zero_net_regression_verdict']}"
    )

    print("\n=== Step 4: spelling-variance robustness delta (THE success criterion) ===")
    step4 = step4_spelling_robustness_delta()
    print(
        f"baseline band-agreement={step4['baseline_band_agreement_rate']['point']:.4f} "
        f"vs candidate={step4['candidate_band_agreement_rate']['point']:.4f} "
        f"(delta={step4['delta_point']:+.4f}, n_matches_verified={step4['n_matches_verified']})"
    )

    ci_meaningful = _ci_meaningful_improvement(
        step4["delta_point"],
        step4["baseline_band_agreement_rate"],
        step4["candidate_band_agreement_rate"],
    )
    go_verdict = step3["zero_net_regression_verdict"] and ci_meaningful

    result = {
        "step1_data_assembly": step1,
        "step2_training": step2,
        "step3_gate_vs_shipped": step3,
        "step4_spelling_robustness_delta": {
            k: v for k, v in step4.items() if k != "candidate_report_full"
        },
        "verdict": {
            "zero_net_regression": step3["zero_net_regression_verdict"],
            "ci_meaningful_spelling_robustness_improvement": ci_meaningful,
            "go_no_go": "GO (promotion candidate -- awaiting GG approval, NOT auto-published)"
            if go_verdict
            else "NO-GO",
        },
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    # Full candidate spelling-robustness report (all categories, not just the
    # trimmed summary above) is written separately -- large (includes every
    # per-(secret,word,variant) drift record).
    (DATA_DIR / "spelling_robustness_report_variant_augmented.json").write_text(
        json.dumps(step4["candidate_report_full"], indent=2) + "\n", encoding="utf-8"
    )

    print(f"\n=== VERDICT: {result['verdict']['go_no_go']} ===")
    print(f"wrote {REPORT_JSON_PATH}")


if __name__ == "__main__":
    main()
