from __future__ import annotations

"""
Ship-step 2 (spec-residual-attack.md ship checklist item 2): re-verify the
L2-patch + L5 combined numbers end-to-end through the REAL production code
path -- vocab.apply_devanagari_patch + embeddings.embed_vocab +
payload.build_payload -- not the probe scripts' parallel reimplementation
(probe_l2_patch_l5_combined.py). This exists specifically to catch any
discrepancy between "the probe says X" and "the actual generator pipeline
does X" (a typo in the patch data file, a formula drift between rival.
scorching_cutoff and what the probe measured, etc.) before shipping.

Two checks:
1. Benchmark parity: embed the hi-en vocab through the production path
   (vocab.load_hien_vocab -> vocab.apply_devanagari_patch -> embeddings.
   embed_vocab), score dim1/dim2 against the frozen 34-secret benchmark with
   the SAME scoring/CI functions the probes used (legitimate reuse -- that's
   the ruler itself, not something under test), and assert the numbers match
   probe_l2_patch_l5_combined.eval_result.json within floating-point noise.
2. L5 live payload check: call payload.build_payload() for real (not a
   reimplementation) for each of the 8 curated L5 secrets with a dummy date,
   and confirm the related word's actual payload entry shows the forced
   rank AND a qsim-derived similarity percentage consistent with "scorching"
   (matching what a player would see in guess_tile.dart's simPct) -- this
   is the check the probe COULDN'T do, since it never touched real payload
   code.

Run (from generator/):
    uv run python -m evals.finetune.verify_ship_l2_l5_e2e
"""

import json
from datetime import date
from pathlib import Path

from embeddings import embed_vocab
from evals.finetune.bootstrap_ci import (
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import _model_override
from evals.finetune.probe_lever_l2_devanagari_hybrid import (
    SHIPPED_MODEL,
    _dim2_for_pairs_hybrid,
    _public_benchmark_dim1_records_hybrid,
    _public_benchmark_dim2_result_hybrid,
    _resolve_actuals_hybrid,
    _shipped_model_dim1_records_34,
    _shipped_model_dim2_records_34,
)
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from payload import build_payload
from rival import band_for_rank
from vocab import apply_devanagari_patch, load_commonsense_overrides, load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
RUN_NAME = "verify_ship_l2_l5_e2e"
COMBINED_RESULT_PATH = DATA_DIR / "probe_l2_patch_l5_combined.eval_result.json"
_TOL = 1e-9  # exact-match tolerance; same deterministic inputs, no reason to drift


def verify_benchmark_parity() -> dict:
    """Build the embedding through the REAL production path and confirm the
    frozen-benchmark dim1/dim2/regression-floor numbers match the combined
    probe's, sourced from vocab.apply_devanagari_patch (the shipped
    function), not a probe-local reimplementation."""
    vocab = load_hien_vocab()
    embed_input = apply_devanagari_patch(vocab)
    with _model_override(SHIPPED_MODEL):
        matrix = embed_vocab(embed_input, "hi-en")
    word_to_idx = {w: i for i, w in enumerate(vocab)}

    hybrid_dim1 = _public_benchmark_dim1_records_hybrid(matrix, word_to_idx)
    hybrid_dim2 = _public_benchmark_dim2_result_hybrid(matrix, word_to_idx)
    shipped_dim1 = _shipped_model_dim1_records_34()
    shipped_dim2 = _shipped_model_dim2_records_34()

    dim1_ci = bootstrap_dim1_spearman_ci(hybrid_dim1)
    dim2_ci = bootstrap_dim2_pass_rate_ci(hybrid_dim2["records"])
    dim1_delta = paired_bootstrap_dim1_delta(shipped_dim1, hybrid_dim1)
    dim2_delta = paired_bootstrap_dim2_delta(shipped_dim2, hybrid_dim2["records"])
    dim1_floor = dim1_regression_floor(shipped_dim1, hybrid_dim1)
    dim2_floor = dim2_regression_floor(shipped_dim2, hybrid_dim2["records"])

    prior = json.loads(COMBINED_RESULT_PATH.read_text(encoding="utf-8"))
    checks = {
        "dim1_point_matches": abs(
            dim1_ci["point"] - prior["benchmark_dim1_spearman_ci"]["point"]
        )
        < _TOL,
        "dim2_point_matches": abs(
            dim2_ci["point"] - prior["benchmark_dim2_pass_rate_ci"]["point"]
        )
        < _TOL,
        "dim1_delta_matches": abs(
            dim1_delta["delta_point"] - prior["dim1_delta_vs_shipped"]["delta_point"]
        )
        < _TOL,
        "dim2_delta_matches": abs(
            dim2_delta["delta_point"] - prior["dim2_delta_vs_shipped"]["delta_point"]
        )
        < _TOL,
        "dim1_floor_matches": dim1_floor == prior["dim1_regression_floor_all_34"],
        "dim2_floor_matches": dim2_floor == prior["dim2_regression_floor_all_34"],
    }

    return {
        "vocab": vocab,
        "word_to_idx": word_to_idx,
        "dim1_spearman_ci": dim1_ci,
        "dim2_pass_rate_ci": dim2_ci,
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim1_regression_floor": dim1_floor,
        "dim2_regression_floor": dim2_floor,
        "parity_checks": checks,
        "all_parity_checks_pass": all(checks.values()),
    }


def verify_l5_live_payloads() -> dict:
    """Call payload.build_payload() FOR REAL (production code, no
    reimplementation) for each of L5's 8 curated secrets, and check the
    related word's actual payload entry."""
    vocab = load_hien_vocab()
    embed_input = apply_devanagari_patch(vocab)
    with _model_override(SHIPPED_MODEL):
        matrix = embed_vocab(embed_input, "hi-en")

    overrides = load_commonsense_overrides()
    n = len(vocab)
    per_word: list[dict] = []
    all_pass = True

    for secret, related in overrides.items():
        if secret not in vocab or related not in vocab:
            per_word.append({"secret": secret, "related": related, "skipped": "not in vocab"})
            continue
        payload = build_payload(vocab, matrix, secret, "hi-en", date(2026, 1, 1), clue="")
        salt = payload["salt"]
        related_hash = None
        import hashlib

        related_hash = hashlib.sha1(f"{related}{salt}".encode()).hexdigest()[:12]  # noqa: S324
        entry = payload["words"].get(related_hash)
        ok = entry is not None
        rank = entry[0] if entry else None
        qsim = entry[1] if entry else None
        similarity = (qsim / 32767.5) - 1.0 if qsim is not None else None
        sim_pct = ((similarity + 1) / 2 * 100) if similarity is not None else None
        band = band_for_rank(rank, n) if rank is not None else None
        band_ok = band in (0, 1)  # scorching or win
        pct_consistent_with_band = sim_pct is not None and sim_pct >= 50.0

        result_ok = ok and band_ok and pct_consistent_with_band
        all_pass = all_pass and result_ok
        per_word.append(
            {
                "secret": secret,
                "related": related,
                "payload_entry_found": ok,
                "rank": rank,
                "band_ordinal": band,
                "band_is_scorching_or_win": band_ok,
                "displayed_similarity_pct": round(sim_pct, 1) if sim_pct is not None else None,
                "pct_consistent_with_scorching_band": pct_consistent_with_band,
                "result_ok": result_ok,
            }
        )

    return {"n_words": len(per_word), "all_pass": all_pass, "per_word": per_word}


def main() -> None:
    print("=== 1. Benchmark parity (production embedding path vs. combined probe) ===")
    parity = verify_benchmark_parity()
    for k, v in parity["parity_checks"].items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print(f"  ALL PARITY CHECKS: {'PASS' if parity['all_parity_checks_pass'] else 'FAIL'}")

    print("\n=== 2. L5 live payload check (real payload.build_payload) ===")
    l5 = verify_l5_live_payloads()
    for r in l5["per_word"]:
        print(
            f"  {r['secret']:10s} -> {r['related']:8s}  rank={r.get('rank')}  "
            f"band={r.get('band_ordinal')}  displayed%={r.get('displayed_similarity_pct')}  "
            f"ok={r['result_ok']}"
        )
    print(f"  ALL L5 LIVE CHECKS: {'PASS' if l5['all_pass'] else 'FAIL'}")

    out = {
        "run_name": RUN_NAME,
        "benchmark_parity": {k: v for k, v in parity.items() if k not in ("vocab", "word_to_idx")},
        "l5_live_payload_check": l5,
        "overall_ship_verification_pass": parity["all_parity_checks_pass"] and l5["all_pass"],
    }
    out_path = DATA_DIR / f"{RUN_NAME}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")
    print(f"\nOVERALL SHIP VERIFICATION: {'PASS' if out['overall_ship_verification_pass'] else 'FAIL'}")


if __name__ == "__main__":
    main()
