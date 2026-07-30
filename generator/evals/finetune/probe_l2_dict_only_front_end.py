from __future__ import annotations

"""
Phase 2 of the L2 full-vocab rebaseline (spec-residual-attack.md, PLAN.md
"L2 full-vocab Devanagari front-end rebaseline"): scores L2 as a near-full-
vocab front-end against the frozen public benchmark -- DICT-SOURCED WORDS
ONLY, not the raw LLM-fallback output.

Why dict-only, not the full devanagari_front_end_vocab_table.json: a random
40-word audit of that table's ~5,236 LLM-resolved (non-dict) entries found a
20% quality-issue rate -- 5% outright garbage (e.g. adrak -> corrupted
nonsense) and 15% TRANSLATIONS instead of transliterations (e.g. learn ->
"sikhein", the Hindi word MEANING "learn", not a phonetic spelling of the
English word "learn"). That includes all 4 flagship collision words
(junoon/registan/jheel/udaasi), which came back corrupted in the full table
despite resolving to correct Devanagari (जुनून/रेगिस्तान/झील/उदासी) in the
earlier 4-word probe (probe_lever_l2_devanagari_hybrid.py) via the identical
llama3.1:8b fallback protocol -- a real, reproducible pipeline defect, not
noise. Scoring the corrupted table would confound "does Devanagari
tokenization help" with "what does embedding random garbage/mistranslations
do to rankings," which is scientifically useless for a ship decision. GG
chose (2026-07-23) to score the dict-only subset instead: 5,231 words from
Aksharantar (a real transliteration corpus, not LLM-hallucinated) plus the 4
flagship words patched in from the already-validated, already-graduated
probe result -- ~49.9% vocab coverage, zero corruption risk, no further GCP
spend, tests the core L2 hypothesis cleanly. Every other vocab word is left
romanized (== baseline), same as the 4-word probe's own design.

Reuses probe_lever_l2_devanagari_hybrid.py's scoring machinery verbatim
(_resolve_actuals_hybrid / _dim2_for_pairs_hybrid / the shipped-model cached
baseline / bootstrap CIs / regression floor) -- only the SUBSTITUTION SET
differs (dict+patch here vs. 4 hand-picked words there). No-leakage: read-only
against every data/training file and config.py. No git operations.

Run (from generator/):
    uv run python -m evals.finetune.probe_l2_dict_only_front_end
"""

import json
from pathlib import Path

from embeddings import embed_vocab
from evals.finetune.bootstrap_ci import (
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import _model_override
from evals.finetune.pmi_mine import AKSHARANTAR_PATH, build_romanized_to_devanagari
from evals.finetune.probe_lever_l2_devanagari_hybrid import (
    SHIPPED_MODEL,
    TARGET_WORDS,
    _dim2_for_pairs_hybrid,
    _public_benchmark_dim1_records_hybrid,
    _public_benchmark_dim2_result_hybrid,
    _resolve_actuals_hybrid,
    _shipped_model_dim1_records_34,
    _shipped_model_dim2_records_34,
    _target_word_summary,
)
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
RUN_NAME = "probe_l2_dict_only_front_end"
FLAGSHIP_PROBE_RESULT_PATH = DATA_DIR / "probe_lever_l2_devanagari_hybrid.eval_result.json"


def load_flagship_patch() -> dict[str, str]:
    """The 4 flagship words' Devanagari spellings, sourced from the ALREADY
    GRADUATED 4-word probe's own result file (not re-guessed, not re-run) --
    full provenance, not fabricated. Raises if that file is missing or a
    target word's resolution is null, rather than silently skipping."""
    result = json.loads(FLAGSHIP_PROBE_RESULT_PATH.read_text(encoding="utf-8"))
    resolution = result["devanagari_resolution"]
    patch = {}
    for w in TARGET_WORDS:
        deva = resolution[w]["devanagari"]
        if not deva:
            raise ValueError(f"flagship word {w!r} has no validated Devanagari in {result}")
        patch[w] = deva
    return patch


def build_dict_only_substitutions() -> dict[str, str]:
    """{romanized_word: devanagari} for every hi-en vocab word with a direct
    Aksharantar dict hit, plus the 4 flagship words patched from the graduated
    probe. Deterministic, reproducible locally -- no LLM call, no GCP."""
    vocab = load_hien_vocab()
    dict_hits = build_romanized_to_devanagari(AKSHARANTAR_PATH)
    substitutions = {w: dict_hits[w] for w in vocab if w in dict_hits}
    substitutions.update(load_flagship_patch())
    return substitutions


def build_hybrid_matrix(substitutions: dict[str, str]):
    """Same positional-alignment pattern as probe_lever_l2_devanagari_hybrid's
    build_hybrid_matrix: substitute Devanagari text at each covered word's
    vocab position before encoding; word_to_idx keys stay the original
    romanized vocab so downstream lookups are unaffected."""
    hien_vocab = load_hien_vocab()
    hybrid_vocab = [substitutions.get(w, w) for w in hien_vocab]
    with _model_override(SHIPPED_MODEL):
        matrix = embed_vocab(hybrid_vocab, "hi-en")
    word_to_idx = {w: i for i, w in enumerate(hien_vocab)}
    return matrix, word_to_idx


def evaluate() -> dict:
    substitutions = build_dict_only_substitutions()
    vocab = load_hien_vocab()
    n_covered = sum(1 for w in vocab if w in substitutions)
    print(f"substitution coverage: {n_covered}/{len(vocab)} ({100 * n_covered / len(vocab):.1f}%)")
    for w in TARGET_WORDS:
        print(f"  flagship {w} -> {substitutions.get(w)!r}")

    matrix, word_to_idx = build_hybrid_matrix(substitutions)

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

    result = {
        "run_name": RUN_NAME,
        "shipped_model": SHIPPED_MODEL,
        "substitution_coverage": {"n_covered": n_covered, "n_vocab": len(vocab)},
        "flagship_words_devanagari": {w: substitutions.get(w) for w in TARGET_WORDS},
        "n_dim1_secrets": len({r["secret"] for r in hybrid_dim1}),
        "n_dim1_scenarios": len(hybrid_dim1),
        "n_dim2_pairs": len(hybrid_dim2["records"]),
        "hybrid_dim1_spearman_ci": hybrid_dim1_ci,
        "hybrid_dim2_pass_rate_ci": hybrid_dim2_ci,
        "shipped_dim1_spearman_ci": shipped_dim1_ci,
        "shipped_dim2_pass_rate_ci": shipped_dim2_ci,
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim1_regression_floor_all_34": dim1_floor,
        "dim2_regression_floor_all_34": dim2_floor,
        "target_words_before_shipped": target_before,
        "target_words_after_hybrid": target_after,
    }
    out_path = DATA_DIR / f"{RUN_NAME}.eval_result.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return result


def main() -> None:
    evaluate()


if __name__ == "__main__":
    main()
