from __future__ import annotations

"""
Dimension 2 — cross-language consistency.

For every translation-paired secret in the FULL daily EN<->hi-en schedule
(60 pairs, not just dimension 1's 25-secret curated sample — this dimension
needs the statistical breadth), asks the single most direct cross-language
question: if a hi-en player guesses the EN secret's exact English
translation, does it rank as a strong ("Scorching"/"Hot") guess against the
hi-en secret?

This is the same question dimension 1 asked for its 25-secret "translation"
subtype, extended to the full 60-pair schedule for a robust headline number,
plus explicit per-pair divergence data so badly-diverging pairs are flagged
individually rather than averaged into a single score (GG review: "flag
pairs where the hi-en model diverges badly... so they're documented, not
silently shipped").
"""

import numpy as np

from embeddings import cosine_similarities, embed_vocab
from evals.harness.pairs import load_daily_pairs
from rival import band_for_rank
from vocab import load_en_vocab, load_hien_vocab

_GOOD_BANDS = {1, 2}  # Scorching, Hot


def run_dimension2() -> dict:
    """Compute cross-language consistency across the full daily schedule."""
    pairs = load_daily_pairs()

    hien_vocab = load_hien_vocab()
    hien_matrix = embed_vocab(hien_vocab, "hi-en")
    hien_idx = {w: i for i, w in enumerate(hien_vocab)}
    n_hien = len(hien_vocab)

    en_vocab_set = set(load_en_vocab())

    records: list[dict] = []
    for en_secret, hien_secret in pairs:
        if hien_secret not in hien_idx:
            records.append(
                {
                    "en_secret": en_secret,
                    "hien_secret": hien_secret,
                    "resolution_error": f"hien secret {hien_secret!r} not in hi-en vocab",
                }
            )
            continue
        if en_secret not in hien_idx:
            # The EN translation word isn't itself present in the combined
            # hi-en vocab (rare — would mean it's outside the top-10k English
            # words AND not manually curated in hinglish.txt).
            records.append(
                {
                    "en_secret": en_secret,
                    "hien_secret": hien_secret,
                    "resolution_error": f"EN translation {en_secret!r} not in hi-en vocab",
                }
            )
            continue

        secret_vec = hien_matrix[hien_idx[hien_secret]]
        sims = cosine_similarities(hien_matrix, secret_vec)
        order = np.argsort(-sims)
        ranks = np.empty(n_hien, dtype=np.int32)
        for rank_minus1, idx in enumerate(order):
            ranks[idx] = rank_minus1 + 1

        rank = int(ranks[hien_idx[en_secret]])
        band = band_for_rank(rank, n_hien)
        records.append(
            {
                "en_secret": en_secret,
                "hien_secret": hien_secret,
                "guess": en_secret,
                "guess_is_valid_en_word": en_secret in en_vocab_set,
                "rank": rank,
                "vocab_size": n_hien,
                "rank_percentile": round(100 * rank / n_hien, 2),
                "band": band,
                "consistent": band in _GOOD_BANDS,
                "resolution_error": None,
            }
        )

    resolved = [r for r in records if r.get("resolution_error") is None]
    consistent = [r for r in resolved if r["consistent"]]

    ranks = [r["rank"] for r in resolved]
    pass_rate = len(consistent) / len(resolved) if resolved else None

    worst = sorted(resolved, key=lambda r: -r["rank"])[:15]

    return {
        "n_pairs": len(pairs),
        "n_resolved": len(resolved),
        "n_resolution_errors": len(records) - len(resolved),
        "pass_rate_scorching_or_hot": pass_rate,
        "median_rank": float(np.median(ranks)) if ranks else None,
        "mean_rank": float(np.mean(ranks)) if ranks else None,
        "median_rank_percentile": float(np.median([r["rank_percentile"] for r in resolved]))
        if resolved
        else None,
        "worst_diverging_pairs": [
            {
                "en_secret": r["en_secret"],
                "hien_secret": r["hien_secret"],
                "rank": r["rank"],
                "rank_percentile": r["rank_percentile"],
                "band": r["band"],
            }
            for r in worst
        ],
        "all_records": records,
    }


if __name__ == "__main__":
    result = run_dimension2()
    print("=== dimension 2 — cross-language consistency ===")
    print(f"  n_pairs: {result['n_pairs']} (resolved: {result['n_resolved']}, "
          f"errors: {result['n_resolution_errors']})")
    print(f"  pass_rate (Scorching/Hot): {result['pass_rate_scorching_or_hot']}")
    print(f"  median_rank: {result['median_rank']} / median_percentile: "
          f"{result['median_rank_percentile']:.2f}%")
    print(f"  mean_rank: {result['mean_rank']}")
    print("\n  worst-diverging pairs:")
    for r in result["worst_diverging_pairs"]:
        print(f"    {r['hien_secret']:12s} <- {r['en_secret']:12s}  "
              f"rank={r['rank']:6d} ({r['rank_percentile']:5.1f}%ile)  band={r['band']}")
