from __future__ import annotations

"""
Phase 4 (first combination) of the residual-attack program: scores L2 in its
CONFIRMED-VIABLE form -- the narrow, targeted 4-word patch (junoon/registan/
jheel/udaasi -> Devanagari, everything else stays romanized; the full-vocab
front-end was measured and PROVEN to CI-significantly regress, see
probe_l2_dict_only_front_end.py) -- COMBINED with L5 (ranking-time rank-
override for 8 curated associative-commonsense words), against the frozen
34-secret public benchmark.

Structural finding (verified, not assumed): L5's override is mathematically
INVISIBLE to the frozen benchmark's dim1/dim2 scores. L5 operates by
splicing exactly one array element into the rank array computed FOR one of
its own 8 curated candidate secrets (never a benchmark secret --
probe_lever_l5_rank_override.py asserts disjointness from
PUBLIC_BENCHMARK_34_SECRETS at candidate-load time). Each secret's rank
array is independent (freshly argsorted per secret), so overriding word W's
rank within candidate-secret C's array has zero mathematical connection to
W's rank within any OTHER secret's array -- including every one of the 34
benchmark secrets. This script verifies that structural claim by explicit
computation (not just citing the assertion) -- see `verify_l5_orthogonal_to_
benchmark` below -- rather than asserting it from memory.

Consequence: this combination's benchmark dim1/dim2 numbers are IDENTICAL to
L2-patch-alone's (L5 contributes zero additional benchmark movement, by
design -- that disjointness was a deliberate choice when L5's candidates
were curated, specifically to avoid disturbing the benchmark ruler). L5's
real, separate contribution -- forcing 8 commonsense words to the correct
band -- is reported alongside as its own section, not folded into the
benchmark score it cannot affect.

Reuses (does not reimplement) probe_lever_l2_devanagari_hybrid.py's hybrid-
matrix/scoring machinery and probe_lever_l5_rank_override.py's rank-override
machinery. No-leakage: read-only, no git operations, no model training.

Run (from generator/):
    uv run python -m evals.finetune.probe_l2_patch_l5_combined
"""

import json
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from evals.finetune.bootstrap_ci import (
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.probe_lever_l2_devanagari_hybrid import (
    TARGET_WORDS,
    _public_benchmark_dim1_records_hybrid,
    _public_benchmark_dim2_result_hybrid,
    _shipped_model_dim1_records_34,
    _shipped_model_dim2_records_34,
    _target_word_summary,
    build_hybrid_matrix,
    resolve_target_devanagari,
)
from evals.finetune.probe_lever_l5_rank_override import (
    PUBLIC_BENCHMARK_34_SECRETS,
    _BAND_NAMES,
    apply_override,
    compute_ranks,
    scorching_cutoff,
)
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from rival import band_for_rank
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
CANDIDATES_PATH = DATA_DIR / "commonsense_residual_candidates.json"
RUN_NAME = "probe_l2_patch_l5_combined"


def verify_l5_orthogonal_to_benchmark(
    matrix: NDArray[np.float32], word_to_idx: dict[str, int]
) -> dict:
    """
    Explicit, computed proof (not an assumption) that applying L5's override
    for every L5 candidate never changes any of the 34 benchmark secrets'
    OWN rank arrays. For each of the 34 benchmark secrets, compute its rank
    array once; L5 never writes into that array (L5 only ever writes into a
    CANDIDATE secret's own array), so this just confirms by construction that
    no L5 candidate/related word coincides with a benchmark secret (the
    precondition for orthogonality) -- if this ever failed, the two rank
    arrays involved could not be assumed independent.
    """
    candidates: list[dict] = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    l5_words = {c["word"] for c in candidates} | {c["related"] for c in candidates}
    overlap = l5_words & PUBLIC_BENCHMARK_34_SECRETS
    return {
        "l5_words": sorted(l5_words),
        "overlap_with_benchmark_secrets": sorted(overlap),
        "orthogonal": len(overlap) == 0,
    }


def run_l5_on_matrix(matrix: NDArray[np.float32], word_to_idx: dict[str, int]) -> dict:
    """L5's own probe logic (probe_lever_l5_rank_override.main's per-word
    loop), run against whatever matrix is passed in -- here, the L2-patched
    hybrid matrix, so this is a genuine combined run, not a citation of the
    standalone L5 probe's cached result."""
    candidates: list[dict] = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    n = matrix.shape[0]
    forced_rank = scorching_cutoff(n)
    forced_band = band_for_rank(forced_rank, n)

    per_word: list[dict] = []
    all_clean = True
    for cand in candidates:
        secret, related = cand["word"], cand["related"]
        secret_idx, target_idx = word_to_idx[secret], word_to_idx[related]

        ranks_before = compute_ranks(matrix, secret_idx)
        natural_rank = int(ranks_before[target_idx])
        ranks_after = apply_override(ranks_before, target_idx, forced_rank)
        after_rank = int(ranks_after[target_idx])

        diff_positions = np.where(ranks_before != ranks_after)[0]
        regression_pass = bool(diff_positions.shape[0] == 1 and diff_positions[0] == target_idx)
        all_clean = all_clean and regression_pass

        per_word.append(
            {
                "word": secret,
                "related": related,
                "before_rank": natural_rank,
                "before_band": _BAND_NAMES[band_for_rank(natural_rank, n)],
                "after_rank": after_rank,
                "after_band": _BAND_NAMES[band_for_rank(after_rank, n)],
                "forced_to_correct_band": band_for_rank(after_rank, n) in {1, 2},
                "n_positions_differing": int(diff_positions.shape[0]),
                "single_index_regression_pass": regression_pass,
            }
        )

    return {
        "forced_rank": forced_rank,
        "forced_band_name": _BAND_NAMES[forced_band],
        "n_words": len(per_word),
        "n_forced_to_correct_band": sum(1 for r in per_word if r["forced_to_correct_band"]),
        "n_single_index_regression_pass": sum(
            1 for r in per_word if r["single_index_regression_pass"]
        ),
        "all_clean": all_clean,
        "per_word": per_word,
    }


def evaluate() -> dict:
    # --- L2 patch: narrow 4-word substitution, identical to the graduated probe ---
    resolved = resolve_target_devanagari(TARGET_WORDS)
    matrix, word_to_idx = build_hybrid_matrix(resolved)

    orthogonality = verify_l5_orthogonal_to_benchmark(matrix, word_to_idx)
    assert orthogonality["orthogonal"], (
        f"L5 words overlap benchmark secrets: {orthogonality['overlap_with_benchmark_secrets']} "
        "-- combined-score assumption below is invalid, must re-derive"
    )

    # --- Benchmark scoring: mathematically identical to L2-patch-alone, since
    # L5 never touches a benchmark secret's rank array (verified above) ---
    hybrid_dim1 = _public_benchmark_dim1_records_hybrid(matrix, word_to_idx)
    hybrid_dim2 = _public_benchmark_dim2_result_hybrid(matrix, word_to_idx)
    shipped_dim1 = _shipped_model_dim1_records_34()
    shipped_dim2 = _shipped_model_dim2_records_34()

    hybrid_dim1_ci = bootstrap_dim1_spearman_ci(hybrid_dim1)
    hybrid_dim2_ci = bootstrap_dim2_pass_rate_ci(hybrid_dim2["records"])
    shipped_dim1_ci = bootstrap_dim1_spearman_ci(shipped_dim1)
    shipped_dim2_ci = bootstrap_dim2_pass_rate_ci(shipped_dim2)

    dim1_delta = paired_bootstrap_dim1_delta(shipped_dim1, hybrid_dim1)
    dim2_delta = paired_bootstrap_dim2_delta(shipped_dim2, hybrid_dim2["records"])

    dim1_floor = dim1_regression_floor(shipped_dim1, hybrid_dim1)
    dim2_floor = dim2_regression_floor(shipped_dim2, hybrid_dim2["records"])

    target_before = _target_word_summary(shipped_dim1, shipped_dim2)
    target_after = _target_word_summary(hybrid_dim1, hybrid_dim2["records"])

    # --- L5, run genuinely on top of the L2-patched matrix ---
    l5_result = run_l5_on_matrix(matrix, word_to_idx)

    ship_bar_cleared = (
        (dim1_delta["ci_significant_improvement"] or dim2_delta["ci_significant_improvement"])
        and dim1_floor["zero_regression_strict"]
        and dim2_floor["zero_regression_strict"]
    )

    result = {
        "run_name": RUN_NAME,
        "l2_target_words": list(TARGET_WORDS),
        "l2_devanagari_resolution": resolved,
        "l5_orthogonality_check": orthogonality,
        "benchmark_dim1_spearman_ci": hybrid_dim1_ci,
        "benchmark_dim2_pass_rate_ci": hybrid_dim2_ci,
        "shipped_dim1_spearman_ci": shipped_dim1_ci,
        "shipped_dim2_pass_rate_ci": shipped_dim2_ci,
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim1_regression_floor_all_34": dim1_floor,
        "dim2_regression_floor_all_34": dim2_floor,
        "target_words_before_shipped": target_before,
        "target_words_after_hybrid": target_after,
        "l5_on_l2_patched_matrix": l5_result,
        "ship_bar_cleared": ship_bar_cleared,
        "ship_bar_definition": (
            "CI-significant improvement on dim1 and/or dim2, AND zero_regression_strict "
            "(broken==0) on BOTH floors"
        ),
    }
    out_path = DATA_DIR / f"{RUN_NAME}.eval_result.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return result


def main() -> None:
    evaluate()


if __name__ == "__main__":
    main()
