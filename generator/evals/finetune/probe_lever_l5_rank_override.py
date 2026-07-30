from __future__ import annotations

"""
Cheap probe for lever L5 (spec-residual-attack.md) -- "knowledge/retrieval
augmentation AT RANKING TIME", explicitly a NON-FINE-TUNING mitigation. No
model is trained or touched here.

Background: docs/known-limitations.md entry 20 documents an associative-
commonsense residual -- world-knowledge facts (a food's taste/color/texture)
that a pure co-occurrence embedding structurally under-ranks, because the
fact is rarely stated as plain text co-occurrence (you learn "watermelon is
red" from cutting one open, not from reading about watermelons). A prior
probe pass hand-curated + no-leakage-verified 8 game-vocab (secret, related-
property-word) edges with justifications --
evals/finetune/data/commonsense_residual_candidates.json -- reused AS-IS
here, not re-derived.

This probe asks: instead of training around the residual (proven
insufficient for the sibling subword-collision residual, see entry 20's
LEVER 1), can the generator's RANK COMPUTATION simply be told the fact
directly, at puzzle-build time, for a specific secret? Recon (trusted,
verified against the actual source below) identified the splice point:
payload._build_payload_core computes `sims = cosine_similarities(matrix,
secret_vec)` -> `order = np.argsort(-sims)` -> a 1-based `ranks` array,
THEN writes every word's [rank, qsim] into words_map. Overwriting exactly
one array element in `ranks` (the related-property word's rank) before that
write is a single-index splice: no re-sort, and (by construction) every
OTHER word's rank is left byte-identical.

This script does NOT edit payload.py, rival.py, or build.py -- it is a
STANDALONE reproduction of the ranking algorithm (reusing the real
embeddings.cosine_similarities and rival.band_for_rank functions, so this
measures the same math a real payload build would use, not a re-implemented
approximation), plus a probe-only override step, for MEASUREMENT ONLY.

Run (from generator/):
    uv run python -m evals.finetune.probe_lever_l5_rank_override
"""

import json
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from embeddings import cosine_similarities, embed_vocab
from rival import band_for_rank
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
CANDIDATES_PATH = DATA_DIR / "commonsense_residual_candidates.json"
RESULT_PATH = DATA_DIR / "probe_lever_l5_rank_override.eval_result.json"

# The frozen public 34-secret benchmark (gauravgandhi2411/hinglish-relatedness-
# benchmark v1.1) -- the "benchmark ruler" this probe must not disturb. Copied
# verbatim from evals/finetune/probe_subword_collision.py's
# PUBLIC_BENCHMARK_34_SECRETS (not imported, to keep this probe fully
# standalone / no accidental coupling to another probe's module state).
PUBLIC_BENCHMARK_34_SECRETS: frozenset[str] = frozenset(
    {
        "registan",
        "jheel",
        "chattan",
        "dhoop",
        "patta",
        "sharm",
        "chinta",
        "mazaa",
        "junoon",
        "udaasi",
        "azaadi",
        "insaaf",
        "waqt",
        "sawaal",
        "kanoon",
        "chaabi",
        "sandook",
        "thaali",
        "tokri",
        "chimni",
        "sadak",
        "sarhad",
        "basti",
        "mohalla",
        "dehat",
        "mithai",
        "dahi",
        "paneer",
        "besan",
        "khichdi",
        "mausi",
        "bhanja",
        "bhanji",
        "judwaa",
    }
)

_BAND_NAMES = {0: "win", 1: "scorching", 2: "hot", 3: "warm", 4: "cold", 5: "freezing"}


def compute_ranks(matrix: NDArray[np.float32], secret_idx: int) -> NDArray[np.int32]:
    """
    Reproduce payload._build_payload_core's rank computation exactly
    (lines 193-200 of payload.py, verified by direct read): cosine
    similarities against the secret vector, descending argsort, then a
    1-based rank assigned per vocab index. Returns an (N,) int32 array
    where ranks[i] is vocab word i's rank against this secret (rank 1 ==
    the secret itself).
    """
    secret_vec = matrix[secret_idx]
    sims = cosine_similarities(matrix, secret_vec)
    order = np.argsort(-sims)  # descending by similarity, same as payload.py
    ranks = np.empty(len(matrix), dtype=np.int32)
    for rank_minus1, idx in enumerate(order):
        ranks[idx] = rank_minus1 + 1
    return ranks


def scorching_cutoff(n: int) -> int:
    """
    Mirror of rival.band_for_rank's scorching threshold: max(50, n*0.001).
    Chosen (per task spec) as the TIGHTER of the two "near" cutoffs
    (scorching vs hot) to make the override maximally decisive/testable.
    """
    return max(50, int(n * 0.001))


def apply_override(
    ranks: NDArray[np.int32], target_idx: int, forced_rank: int
) -> NDArray[np.int32]:
    """
    Return a COPY of `ranks` with ranks[target_idx] overwritten to
    forced_rank. This is the L5 splice point: a single array-element
    overwrite performed on a copy of the natural `ranks` array, BEFORE it
    would be written into words_map in the real pipeline -- not a re-sort,
    so every other index is left byte-identical by construction. Ranks
    become non-bijective for this secret (forced_rank may already be held
    by another word) -- an accepted, documented tradeoff per the task spec,
    verified harmless below by reading rival.band_for_rank's actual
    implementation (it consumes only rank+n, never assumes uniqueness).
    """
    out = ranks.copy()
    out[target_idx] = forced_rank
    return out


def main() -> dict:
    """Run the full L5 probe and return the report dict (also written to RESULT_PATH)."""
    candidates: list[dict] = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))

    vocab = load_hien_vocab()
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    n = len(vocab)
    matrix = embed_vocab(vocab, "hi-en")

    assert matrix.shape[0] == n, (
        f"embedding matrix rows ({matrix.shape[0]}) != vocab length ({n}) -- "
        "cache/vocab mismatch, would invalidate every rank computed below"
    )

    forced_rank = scorching_cutoff(n)
    forced_band = band_for_rank(forced_rank, n)

    # Which vocab index does each of the 34 frozen public-benchmark secrets
    # occupy? Used below to confirm the override never touches a benchmark
    # secret's own rank-1 slot for a DIFFERENT secret's ranking (i.e. rules
    # out any collision with the benchmark ruler, not just "looks fine").
    benchmark_secret_idx = {
        s: word_to_idx[s] for s in PUBLIC_BENCHMARK_34_SECRETS if s in word_to_idx
    }
    missing_benchmark_secrets = sorted(PUBLIC_BENCHMARK_34_SECRETS - set(word_to_idx))

    per_word_results: list[dict] = []
    all_regressions_clean = True

    for cand in candidates:
        secret = cand["word"]
        related = cand["related"]

        assert secret in word_to_idx, f"candidate secret {secret!r} not in current hi-en vocab"
        assert related in word_to_idx, f"related word {related!r} not in current hi-en vocab"
        # These 8 curated secrets/related words must be disjoint from the frozen
        # 34-secret benchmark set -- otherwise overriding one would risk moving
        # the benchmark's own ruler, not just a game-vocab word's rank.
        assert secret not in PUBLIC_BENCHMARK_34_SECRETS, (
            f"{secret!r} collides with a frozen public benchmark secret -- unsafe to override"
        )
        assert related not in PUBLIC_BENCHMARK_34_SECRETS, (
            f"{related!r} collides with a frozen public benchmark secret -- unsafe to override"
        )

        secret_idx = word_to_idx[secret]
        target_idx = word_to_idx[related]

        ranks_before = compute_ranks(matrix, secret_idx)
        natural_rank = int(ranks_before[target_idx])
        natural_band = band_for_rank(natural_rank, n)

        ranks_after = apply_override(ranks_before, target_idx, forced_rank)
        after_rank = int(ranks_after[target_idx])
        after_band = band_for_rank(after_rank, n)

        # --- Regression check: diff the FULL rank array, not a claim. ---
        diff_positions = np.where(ranks_before != ranks_after)[0]
        expected_diff_positions = np.array([target_idx], dtype=diff_positions.dtype)
        regression_pass = bool(
            diff_positions.shape[0] == 1 and diff_positions[0] == target_idx
        )
        if not regression_pass:
            all_regressions_clean = False

        # --- Rank-collision finding: who else naturally held forced_rank? ---
        collision_word = None
        collision_idx_matches = np.where(ranks_before == forced_rank)[0]
        if collision_idx_matches.size > 0:
            collision_word = vocab[int(collision_idx_matches[0])]

        # --- Explicit benchmark-ruler cross-check: none of the 34 frozen
        # secrets' OWN rank position (against this same probe secret) moved.
        benchmark_secret_ranks_unaffected = all(
            ranks_before[idx] == ranks_after[idx] for idx in benchmark_secret_idx.values()
        )

        per_word_results.append(
            {
                "word": secret,
                "gloss": cand["gloss"],
                "related": related,
                "related_gloss": cand["related_gloss"],
                "vocab_size_at_curation": cand["vocab_size"],
                "recorded_related_rank_at_curation": cand["related_rank"],
                "vocab_size_now": n,
                "before": {
                    "rank": natural_rank,
                    "band_ordinal": natural_band,
                    "band_name": _BAND_NAMES[natural_band],
                },
                "after": {
                    "rank": after_rank,
                    "band_ordinal": after_band,
                    "band_name": _BAND_NAMES[after_band],
                },
                "regression_check": {
                    "method": (
                        "full-array diff: np.where(ranks_before != ranks_after) over all "
                        f"{n} vocab positions"
                    ),
                    "n_positions_differing": int(diff_positions.shape[0]),
                    "differing_indices": diff_positions.tolist(),
                    "expected_only_target_idx": int(target_idx),
                    "pass": regression_pass,
                },
                "rank_collision": {
                    "forced_rank": forced_rank,
                    "originally_held_by": collision_word,
                    "harmless_reasoning": (
                        "rival.band_for_rank(rank, n) is a pure function of (rank, n) only "
                        "(verified by reading its implementation) -- it never dereferences a "
                        "word or assumes the rank->word mapping is bijective, so two words "
                        "sharing forced_rank both resolve to the same (correct) band with no "
                        "exception, no ambiguous lookup, and no crash in this probe's own "
                        "rank/band computation."
                    ),
                },
                "benchmark_ruler_check": {
                    "34_secrets_own_ranks_unaffected": benchmark_secret_ranks_unaffected,
                },
            }
        )

    report = {
        "probe": "lever_l5_rank_override",
        "spec_ref": "spec-residual-attack.md lever L5",
        "non_fine_tuning": True,
        "production_files_edited": [],
        "vocab_size_now": n,
        "forced_rank": forced_rank,
        "forced_rank_formula": "max(50, int(n * 0.001))  # tightest 'scorching' cutoff",
        "forced_band_ordinal": forced_band,
        "forced_band_name": _BAND_NAMES[forced_band],
        "missing_benchmark_secrets_in_current_vocab": missing_benchmark_secrets,
        "results": per_word_results,
        "regression_summary": {
            "n_words_tested": len(per_word_results),
            "n_words_zero_side_effect": sum(
                1 for r in per_word_results if r["regression_check"]["pass"]
            ),
            "all_clean": all_regressions_clean,
        },
    }

    RESULT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = main()
    print(f"\n=== lever L5 rank-override probe ===")
    print(f"vocab_size_now: {result['vocab_size_now']}")
    print(
        f"forced_rank: {result['forced_rank']} -> "
        f"{result['forced_band_name']} (ordinal {result['forced_band_ordinal']})"
    )
    if result["missing_benchmark_secrets_in_current_vocab"]:
        print(
            "WARNING missing benchmark secrets in current vocab: "
            f"{result['missing_benchmark_secrets_in_current_vocab']}"
        )
    for r in result["results"]:
        print(
            f"  {r['word']:10s} -> {r['related']:8s}  "
            f"before: rank {r['before']['rank']:>5d} ({r['before']['band_name']:9s})  "
            f"after: rank {r['after']['rank']:>5d} ({r['after']['band_name']:9s})  "
            f"regression_pass={r['regression_check']['pass']}  "
            f"collision_with={r['rank_collision']['originally_held_by']}"
        )
    summary = result["regression_summary"]
    print(
        f"\nregression summary: {summary['n_words_zero_side_effect']}/"
        f"{summary['n_words_tested']} clean, all_clean={summary['all_clean']}"
    )
    print(f"\nwrote {RESULT_PATH}")
