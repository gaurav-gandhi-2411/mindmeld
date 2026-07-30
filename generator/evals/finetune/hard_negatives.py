from __future__ import annotations

"""
Hard-negative mining (spec-hinglish-diagnostic-sweep.md Step 1b, objective
alignment). The game scores by RANK against the whole vocab; MultipleNegatives
RankingLoss's default in-batch negatives are just "whatever else is in this
batch" -- mostly unrelated, easy negatives a model already separates well.
This mines a genuinely confusable negative per MNRL anchor: a vocab word that
the OFF-THE-SHELF (pre-fine-tune) model already ranks moderately close to the
anchor -- close enough to be a real confusion risk, far enough that it isn't
a near-duplicate/morphological variant of the true positive.

Rank band: [HARD_NEG_RANK_LO, HARD_NEG_RANK_HI] out of the full hi-en vocab
(currently 10,462 words) -- rank ~50-500 is "the model currently thinks this
is somewhat related" without being a top-49 near-miss that might itself be a
legitimate synonym mislabeled as a negative (mirrors dim1_source's own
near/mid/far tier-boundary caution).

Excludes: the true positive itself, anything within edit-distance 3 of the
anchor (avoid morphological near-duplicates, same guard as
gen_dim1_scenarios.py's far-tier sampling), and all held-out
secrets/translations (same no-leakage guarantee as every other source).

Run: uv run python -m evals.finetune.hard_negatives
"""

import json
from pathlib import Path

import numpy as np

from embeddings import cosine_similarities, embed_vocab
from evals.finetune.split import load_split
from payload import levenshtein
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
HARD_NEG_RANK_LO = 50
HARD_NEG_RANK_HI = 500
MIN_LEVENSHTEIN = 4


def _held_out(split: dict) -> set[str]:
    return {w.lower() for w in split["held_out_secrets"]} | {
        w.lower() for w in split["held_out_en_translations"]
    }


def mine_hard_negatives(mnrl_path: Path, out_path: Path) -> dict:
    split = load_split()
    held_out = _held_out(split)

    records = []
    for line in mnrl_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))

    vocab = load_hien_vocab()
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    matrix = embed_vocab(vocab, "hi-en")  # off-the-shelf per config.MODELS default
    n = len(vocab)

    out_records = []
    n_no_anchor_in_vocab = 0
    n_no_candidate_found = 0
    rank_cache: dict[str, np.ndarray] = {}

    for rec in records:
        anchor = rec["anchor"]
        positive = rec["positive"]
        if anchor not in word_to_idx:
            n_no_anchor_in_vocab += 1
            continue
        if anchor not in rank_cache:
            sims = cosine_similarities(matrix, matrix[word_to_idx[anchor]])
            order = np.argsort(-sims)
            ranks = np.empty(n, dtype=np.int32)
            for rank_minus1, idx in enumerate(order):
                ranks[idx] = rank_minus1 + 1
            rank_cache[anchor] = ranks
            rank_cache[f"{anchor}__order"] = order  # type: ignore[assignment]

        order = rank_cache[f"{anchor}__order"]
        candidate = None
        for idx in order[HARD_NEG_RANK_LO : HARD_NEG_RANK_HI + 1]:
            word = vocab[idx]
            wl = word.lower()
            if wl == positive.lower() or wl == anchor.lower():
                continue
            if wl in held_out:
                continue
            if levenshtein(wl, anchor.lower()) < MIN_LEVENSHTEIN:
                continue
            candidate = word
            break
        if candidate is None:
            n_no_candidate_found += 1
            continue
        out_records.append({**rec, "negative": candidate})

    with out_path.open("w", encoding="utf-8") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")

    stats = {
        "n_input_records": len(records),
        "n_output_records": len(out_records),
        "n_no_anchor_in_vocab": n_no_anchor_in_vocab,
        "n_no_candidate_found": n_no_candidate_found,
        "rank_band": [HARD_NEG_RANK_LO, HARD_NEG_RANK_HI],
    }
    return stats


if __name__ == "__main__":
    stats = mine_hard_negatives(
        DATA_DIR / "train_mnrl_pairs.jsonl", DATA_DIR / "train_mnrl_pairs_hard_neg.jsonl"
    )
    print(json.dumps(stats, indent=2))
