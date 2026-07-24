from __future__ import annotations

"""
One-off recomputation script (not part of the standard eval harness) to
answer a specific question precisely: what are the CURRENT, definitive
task-appropriate-suite numbers for the shipped model vs its 7 comparators,
and do any of them need to change post the two latest fixes (band-
calibration floor, alias-fold spelling invariance)?

Reasoning for WHAT needs recomputing (verified by reading the actual code,
not assumed):
  - The alias-fold extension (vocab/hi-en-aliases.txt) never touches
    vocab.load_hien_vocab()'s returned list (confirmed: aliases are a
    separate lookup-fold table, consumed only by normalize.py/payload.py,
    never fed into embed_vocab). It has ZERO effect on any bakeoff number.
  - vocab.apply_devanagari_patch (the L2 patch, incl. `sharm`) is called
    ONLY by production build scripts (build.py/build_onboarding.py/
    build_packs.py) and dedicated ship-verification scripts -- NEVER by
    dimension1_ranking.py, benchmark_bakeoff.py, or eval_model.py.
    Confirmed via `grep -rn apply_devanagari_patch`. So the bakeoff's
    dim1_records/dim2_records (already checkpointed, no re-embedding
    needed) are UNAFFECTED by the L2 patch -- they always measured raw
    romanized-text embedding behavior, weights-only, same for all 8
    models. This was already true when the original bakeoff ran; nothing
    since has changed it.
  - rival.band_for_rank's warm-floor fix (900) changes ONLY how an
    already-computed actual_rank maps to actual_band. dim1 Spearman,
    dim2 pass-rate (dim2's "consistent" check uses _GOOD_BANDS={1,2} --
    scorching/hot -- untouched by the warm-only floor), NDCG/MRR/Recall/
    Precision/top-weighted-correlation (all rank-and-tier based, never
    band-based) are therefore UNCHANGED. band_accuracy, band_confusion,
    per_band_pr DO need recomputation from the cached actual_rank values.
    band_calibration_error (ECE) is claimed invariant (rank-percentile-
    based, never uses actual_band) -- this script recomputes it directly
    to verify that claim rather than trust it.

What this script does, concretely:
  1. Loads the 8 already-checkpointed bakeoff_raw/*.json files (dim1
     Spearman, dim2 pass-rate, topheavy marginal CIs are read as-is --
     verified unaffected, not recomputed).
  2. Recomputes actual_band/in_expected_band/band_accuracy/band_confusion/
     per_band_pr/band_ece for the shipped model using the CURRENT
     rival.band_for_rank (post-floor-fix), from the cached actual_rank
     values -- no re-embedding.
  3. Computes PAIRED bootstrap deltas (shipped vs each of the 7
     comparators) for the topheavy suite (NDCG@k/Recall@k/Precision@k/MRR
     via the existing paired_bootstrap_topheavy_delta helper) and for
     top_weighted_correlation (a paired version written here, mirroring
     paired_bootstrap_dim1_delta exactly, since bootstrap_ci.py only has
     a marginal version of that one metric) -- this did NOT exist as a
     formal significance test in the original Workstream A bakeoff run
     (only marginal per-model CIs were computed there, plus an eyeballed
     point-estimate comparison), so this closes a real rigor gap.

Run: uv run python -m evals.finetune.recompute_current_state
Output: evals/finetune/data/current_state_report.json
"""

import json
from pathlib import Path

import numpy as np

from evals.finetune.bootstrap_ci import (
    N_BOOT,
    SEED,
    _dim1_by_secret,
    _dim1_top_weighted_corr_for_secrets,
)
from evals.finetune.probe_l2_collision_scan_extension import paired_bootstrap_topheavy_delta
from evals.harness import topheavy
from rival import band_for_rank
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
RAW_DIR = DATA_DIR / "bakeoff_raw"
SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"

CANDIDATE_MODELS = [
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "l3cube-pune/indic-sentence-bert-nli",
    "google/muril-base-cased",
    "BAAI/bge-m3",
    "intfloat/multilingual-e5-large",
    "ibm-granite/granite-embedding-311m-multilingual-r2",
    "Qwen/Qwen3-Embedding-0.6B",
]


def _slug(model_name: str) -> str:
    return model_name.replace("/", "__")


def _load_checkpoint(model_name: str) -> dict:
    path = RAW_DIR / f"{_slug(model_name)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _band_accuracy(records: list[dict]) -> float | None:
    if not records:
        return None
    return sum(1 for r in records if r["in_expected_band"]) / len(records)


def recompute_bands(dim1_records: list[dict], n: int) -> dict:
    """Recompute actual_band/in_expected_band for every RESOLVED record
    (actual_rank is not None) using the CURRENT band_for_rank, from the
    already-cached actual_rank -- no re-embedding. Returns a NEW records
    list (does not mutate the input) plus derived band_accuracy.
    """
    updated: list[dict] = []
    for r in dim1_records:
        if r["actual_rank"] is None:
            updated.append(dict(r))
            continue
        new_band = band_for_rank(r["actual_rank"], n)
        rec = dict(r)
        rec["actual_band"] = new_band
        rec["in_expected_band"] = new_band in r["expected_bands"]
        updated.append(rec)

    resolved = [r for r in updated if r["actual_rank"] is not None]
    by_tier = {t: [r for r in resolved if r["tier"] == t] for t in ("near", "mid", "far")}
    band_accuracy = {
        "overall": _band_accuracy(resolved),
        "near": _band_accuracy(by_tier["near"]),
        "mid": _band_accuracy(by_tier["mid"]),
        "far": _band_accuracy(by_tier["far"]),
    }
    return {
        "records": updated,
        "band_accuracy": band_accuracy,
        "band_confusion": topheavy.band_confusion_matrix(resolved),
        "per_band_pr": topheavy.per_band_precision_recall(resolved),
    }


def paired_bootstrap_top_weighted_corr_delta(
    baseline_records: list[dict],
    candidate_records: list[dict],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    """Paired cluster-bootstrap (by secret) delta CI for top_weighted_correlation
    -- mirrors bootstrap_ci.paired_bootstrap_dim1_delta exactly, swapping in
    _dim1_top_weighted_corr_for_secrets. No formal paired version of this
    existed before (only a marginal per-model CI, bootstrap_top_weighted_
    correlation_ci) -- this closes that gap for the leadership-claim check.
    """
    base_by_secret = _dim1_by_secret(baseline_records)
    cand_by_secret = _dim1_by_secret(candidate_records)
    secrets = sorted(set(base_by_secret) & set(cand_by_secret))
    missing = set(base_by_secret) ^ set(cand_by_secret)
    base_point = _dim1_top_weighted_corr_for_secrets(base_by_secret, secrets)
    cand_point = _dim1_top_weighted_corr_for_secrets(cand_by_secret, secrets)
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        b = _dim1_top_weighted_corr_for_secrets(base_by_secret, resample)
        c = _dim1_top_weighted_corr_for_secrets(cand_by_secret, resample)
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
        "secret_mismatch": sorted(missing) if missing else None,
        "n_valid_bootstrap_draws": len(deltas),
    }


def main() -> None:
    n = len(load_hien_vocab())
    print(f"hi-en vocab size (for band recompute): {n:,}")
    assert n == 10495, f"vocab size changed unexpectedly: {n}"

    checkpoints = {m: _load_checkpoint(m) for m in [SHIPPED_MODEL, *CANDIDATE_MODELS]}
    shipped_ck = checkpoints[SHIPPED_MODEL]

    print("Recomputing bands for shipped model under CURRENT band_for_rank...")
    shipped_band_recompute = recompute_bands(shipped_ck["dim1_records"], n)

    print("Recomputing bands for shipped model under the OLD (pre-fix) formula...")

    def old_band_for_rank(rank: int, nn: int) -> int:
        if rank == 1:
            return 0
        scorching_max = max(50, int(nn * 0.001))
        if rank <= scorching_max:
            return 1
        hot_max = max(500, int(nn * 0.01))
        if rank <= hot_max:
            return 2
        warm_max = int(nn * 0.05)  # no floor -- the pre-fix formula
        if rank <= warm_max:
            return 3
        cold_max = int(nn * 0.25)
        if rank <= cold_max:
            return 4
        return 5

    old_updated = []
    for r in shipped_ck["dim1_records"]:
        if r["actual_rank"] is None:
            old_updated.append(dict(r))
            continue
        b = old_band_for_rank(r["actual_rank"], n)
        rec = dict(r)
        rec["actual_band"] = b
        rec["in_expected_band"] = b in r["expected_bands"]
        old_updated.append(rec)
    old_resolved = [r for r in old_updated if r["actual_rank"] is not None]
    old_by_tier = {t: [r for r in old_resolved if r["tier"] == t] for t in ("near", "mid", "far")}
    old_band_accuracy = {
        "overall": _band_accuracy(old_resolved),
        "near": _band_accuracy(old_by_tier["near"]),
        "mid": _band_accuracy(old_by_tier["mid"]),
        "far": _band_accuracy(old_by_tier["far"]),
    }
    old_band_confusion = topheavy.band_confusion_matrix(old_resolved)
    old_per_band_pr = topheavy.per_band_precision_recall(old_resolved)

    print("Verifying ECE-invariance claim by recomputing directly...")
    ece_current = topheavy.band_calibration_error(shipped_band_recompute["records"], n)
    ece_old = topheavy.band_calibration_error(old_resolved, n)

    print("Computing paired bootstrap deltas (shipped vs each comparator) for the topheavy suite...")
    paired_topheavy: dict[str, dict] = {}
    paired_twc: dict[str, dict] = {}
    for comparator in CANDIDATE_MODELS:
        print(f"  vs {comparator} ...")
        comp_records = checkpoints[comparator]["dim1_records"]
        paired_topheavy[comparator] = paired_bootstrap_topheavy_delta(
            comp_records, shipped_ck["dim1_records"]
        )
        paired_twc[comparator] = paired_bootstrap_top_weighted_corr_delta(
            comp_records, shipped_ck["dim1_records"]
        )

    out = {
        "vocab_size": n,
        "note": (
            "dim1_spearman_ci/dim2_pass_rate_ci/topheavy_ci(marginal)/"
            "top_weighted_correlation_ci below are READ AS-IS from the existing "
            "bakeoff_raw checkpoints -- verified unaffected by the alias-fold and "
            "L2-patch changes (neither touches vocab.load_hien_vocab()'s embedded "
            "list or dimension1_ranking's rank computation), and by the band-floor "
            "fix (rank-based, not band-based). Only the band_* fields below were "
            "actually recomputed by this script."
        ),
        "shipped_model": SHIPPED_MODEL,
        "shipped_dim1_spearman_ci": shipped_ck["dim1_spearman_ci"],
        "shipped_dim2_pass_rate_ci": shipped_ck["dim2_pass_rate_ci"],
        "shipped_topheavy_ci_marginal": shipped_ck["topheavy_ci"],
        "shipped_top_weighted_correlation_ci_marginal": shipped_ck["top_weighted_correlation_ci"],
        "band_calibration": {
            "current_formula": {
                "band_accuracy": shipped_band_recompute["band_accuracy"],
                "band_confusion": shipped_band_recompute["band_confusion"],
                "per_band_pr": shipped_band_recompute["per_band_pr"],
                "ece": ece_current,
            },
            "old_formula_for_comparison": {
                "band_accuracy": old_band_accuracy,
                "band_confusion": old_band_confusion,
                "per_band_pr": old_per_band_pr,
                "ece": ece_old,
            },
        },
        "paired_bootstrap_topheavy_vs_comparators": paired_topheavy,
        "paired_bootstrap_top_weighted_correlation_vs_comparators": paired_twc,
    }

    out_path = DATA_DIR / "current_state_report.json"
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
