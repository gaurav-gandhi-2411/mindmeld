from __future__ import annotations

"""
Ship-step 2 (same pattern as verify_ship_l2_l5_e2e.py) for the L2 patch's 5th
entry (`sharm`, graduated by probe_l2_collision_scan_extension.py's n=1
bisection): re-verify the staged numbers end-to-end through the REAL
production code path -- vocab.load_hien_vocab -> vocab.apply_devanagari_patch
-> embeddings.embed_vocab -- not the probe's parallel reimplementation
(probe_l2_collision_scan_extension.py's build_hybrid_matrix, which never
touches the live patch file). This exists specifically to catch any
discrepancy between "the probe says X" and "the actual generator pipeline
does X" (a typo in the live patch file, a formula drift) BEFORE the live
vocab/hi-en-devanagari-patch.txt edit is committed.

Reuses (legitimate -- the ruler itself, not something under test):
  - benchmark_bakeoff.load_combined_dim1_scenarios / combined_dim2_pairs:
    the SAME 42-secret/379-scenario (dim1) + 50-pair (dim2) combined test
    set the extension probe scored against.
  - probe_lever_l2_devanagari_hybrid._resolve_actuals_hybrid /
    _dim2_for_pairs_hybrid: matrix/word_to_idx-parameterized clones of the
    frozen dimension1_ranking._resolve_actuals / eval_model.dim2_for_pairs
    scoring functions (already reused by verify_ship_l2_l5_e2e.py for the
    same reason).
  - probe_l2_collision_scan_extension._shipped_baseline /
    paired_bootstrap_topheavy_delta / _no_topheavy_regression: the exact
    baseline loader + topheavy paired-bootstrap gate the staged n=1 result
    was computed with.
  - regression.dim1_regression_floor / dim2_regression_floor: the zero-
    broken-pairs gate.

One check: benchmark parity. Build the embedding through the REAL
production path (vocab.apply_devanagari_patch reading the LIVE file, now
5 entries, no monkeypatching, no staging file), score dim1/dim2 + the
regression floor + the topheavy paired-bootstrap delta against the SAME
unpatched-shipped-model baseline the probe used, and assert every number
matches evals/finetune/data/probe_l2_collision_scan_extension_n1.eval_result
.json within floating-point/bootstrap-sampling noise (both runs use the
same fixed SEED=42/N_BOOT=10000 in bootstrap_ci.py on identical inputs, so
an exact-match tolerance is appropriate -- no reason to drift).

Run (from generator/):
    uv run python -m evals.finetune.verify_ship_l2_extension_e2e
"""

import json
from pathlib import Path

from embeddings import embed_vocab
from evals.finetune.benchmark_bakeoff import combined_dim2_pairs, load_combined_dim1_scenarios
from evals.finetune.eval_model import _model_override
from evals.finetune.probe_l2_collision_scan_extension import (
    SHIPPED_MODEL,
    _no_topheavy_regression,
    _shipped_baseline,
    paired_bootstrap_topheavy_delta,
)
from evals.finetune.probe_lever_l2_devanagari_hybrid import (
    _dim2_for_pairs_hybrid,
    _resolve_actuals_hybrid,
)
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from evals.finetune.split import load_split
from vocab import apply_devanagari_patch, load_devanagari_patch, load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
RUN_NAME = "verify_ship_l2_extension_e2e"
STAGED_RESULT_PATH = DATA_DIR / "probe_l2_collision_scan_extension_n1.eval_result.json"
EXPECTED_PATCH_WORDS = ("jheel", "junoon", "registan", "sharm", "udaasi")
_TOL = 1e-9  # exact-match tolerance; same deterministic inputs, no reason to drift


def verify_benchmark_parity() -> dict:
    """Build the embedding through the REAL production path (live 5-entry
    vocab/hi-en-devanagari-patch.txt) and confirm the combined-test-set
    dim1/dim2/regression-floor/topheavy-delta numbers match the staged
    n=1 extension probe's, sourced from vocab.apply_devanagari_patch (the
    shipped function reading the live file), not a probe-local
    reimplementation."""
    live_patch = load_devanagari_patch()
    patch_check = {
        "n_live_patch_words": len(live_patch),
        "live_patch_words": sorted(live_patch),
        "matches_expected_5": sorted(live_patch) == sorted(EXPECTED_PATCH_WORDS),
    }

    vocab = load_hien_vocab()
    embed_input = apply_devanagari_patch(vocab)
    with _model_override(SHIPPED_MODEL):
        matrix = embed_vocab(embed_input, "hi-en")
    word_to_idx = {w: i for i, w in enumerate(vocab)}

    split = load_split()
    test_secrets = set(split["test_secrets"])

    raw_scenarios = load_combined_dim1_scenarios(test_secrets)
    cand_dim1 = _resolve_actuals_hybrid(raw_scenarios, matrix, word_to_idx)
    dim2_pairs = combined_dim2_pairs(test_secrets)
    cand_dim2 = _dim2_for_pairs_hybrid(dim2_pairs, matrix, word_to_idx)

    baseline = _shipped_baseline()
    dim1_floor = dim1_regression_floor(baseline["dim1_records"], cand_dim1)
    dim2_floor = dim2_regression_floor(baseline["dim2_records"], cand_dim2["records"])
    topheavy_delta = paired_bootstrap_topheavy_delta(baseline["dim1_records"], cand_dim1)
    zero_net_regression = (
        dim1_floor["zero_regression_strict"]
        and dim2_floor["zero_regression_strict"]
        and _no_topheavy_regression(topheavy_delta)
    )

    staged = json.loads(STAGED_RESULT_PATH.read_text(encoding="utf-8"))
    staged_th = staged["topheavy_paired_delta"]

    def _mrr_match() -> bool:
        return (
            abs(topheavy_delta["mrr"]["delta_point"] - staged_th["mrr"]["delta_point"]) < _TOL
        )

    def _ndcg_match() -> bool:
        return all(
            abs(
                topheavy_delta["ndcg"][k]["delta_point"] - staged_th["ndcg"][str(k)]["delta_point"]
            )
            < _TOL
            for k in (10, 50, 100)
        )

    def _recall_match() -> bool:
        return all(
            abs(
                topheavy_delta["recall"][k]["delta_point"]
                - staged_th["recall"][str(k)]["delta_point"]
            )
            < _TOL
            for k in (10, 50, 100)
        )

    checks = {
        "n_patch_words_matches": len(live_patch) == staged["n_patch_words"],
        "patch_words_match": sorted(live_patch) == staged["patch_words"],
        "dim1_floor_n_fixed_matches": dim1_floor["n_fixed"]
        == staged["dim1_regression_floor"]["n_fixed"],
        "dim1_floor_n_broken_matches": dim1_floor["n_broken"]
        == staged["dim1_regression_floor"]["n_broken"],
        "dim1_floor_zero_broken": dim1_floor["n_broken"] == 0,
        "dim2_floor_n_fixed_matches": dim2_floor["n_fixed"]
        == staged["dim2_regression_floor"]["n_fixed"],
        "dim2_floor_n_broken_matches": dim2_floor["n_broken"]
        == staged["dim2_regression_floor"]["n_broken"],
        "dim2_floor_zero_broken": dim2_floor["n_broken"] == 0,
        "mrr_delta_matches": _mrr_match(),
        "ndcg_delta_matches": _ndcg_match(),
        "recall_delta_matches": _recall_match(),
        "zero_net_regression_verdict_matches": zero_net_regression
        == staged["zero_net_regression_verdict"],
    }

    return {
        "patch_check": patch_check,
        "dim1_regression_floor": dim1_floor,
        "dim2_regression_floor": dim2_floor,
        "topheavy_paired_delta": topheavy_delta,
        "zero_net_regression_verdict": zero_net_regression,
        "parity_checks": checks,
        "all_parity_checks_pass": patch_check["matches_expected_5"] and all(checks.values()),
    }


def main() -> None:
    print("=== Benchmark parity (production embedding path vs. staged n=1 extension probe) ===")
    parity = verify_benchmark_parity()
    print(f"  live patch words: {parity['patch_check']['live_patch_words']}")
    for k, v in parity["parity_checks"].items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print(f"  ALL PARITY CHECKS: {'PASS' if parity['all_parity_checks_pass'] else 'FAIL'}")

    out = {
        "run_name": RUN_NAME,
        "benchmark_parity": parity,
        "overall_ship_verification_pass": parity["all_parity_checks_pass"],
    }
    out_path = DATA_DIR / f"{RUN_NAME}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")
    overall = "PASS" if out["overall_ship_verification_pass"] else "FAIL"
    print(f"\nOVERALL SHIP VERIFICATION: {overall}")


if __name__ == "__main__":
    main()
