from __future__ import annotations

"""
Held-out evaluation harness for the hi-en fine-tune — reuses the production
dimension1/dimension2 computation primitives (rank tables, band_for_rank,
Spearman) but parameterizes them by an explicit secret/pair filter, so the
SAME numbers reported in evals/reports/baseline_report.md can be recomputed
restricted to dev-only or test-only secrets for ANY candidate model
(off-the-shelf baseline or fine-tuned checkpoint).

This module does NOT mutate evals/scenarios/dim1_hien.json or
vocab/secrets_hi-en.txt — it filters in memory at read time. See split.py's
docstring for why: those are shared production fixtures used elsewhere
(baseline reports, payload generation) and must stay intact.

Model swapping: `config.MODELS` is a module-level dict shared by reference
with everything that does `from config import MODELS` (embeddings.py
included) — temporarily assigning `config.MODELS["hi-en"] = <path-or-hf-id>`
inside `with _model_override(...):` makes embed_vocab load that checkpoint
for the duration of the block, with no changes to the file on disk. The
embedding file-cache (embeddings.embed_vocab) keys on (model_name, vocab),
so the off-the-shelf model and the fine-tuned checkpoint never collide.
"""

import json
from contextlib import contextmanager
from pathlib import Path

import numpy as np

import config
from embeddings import cosine_similarities, embed_vocab
from evals.finetune.split import FORCED_TEST_SECRETS, load_split
from evals.harness.dimension1_ranking import (
    _TIER_ORDINAL,
    _band_accuracy,
    _monotonicity,
    _resolve_actuals,
)
from evals.harness.metrics import spearman_correlation
from evals.harness.pairs import load_daily_pairs
from rival import band_for_rank
from vocab import load_hien_vocab

SCENARIOS_PATH = Path(__file__).parent.parent / "scenarios" / "dim1_hien.json"
_GOOD_BANDS = {1, 2}

OFF_THE_SHELF_MODEL = "l3cube-pune/indic-sentence-bert-nli"


@contextmanager
def _model_override(model_name_or_path: str):
    original = config.MODELS["hi-en"]
    config.MODELS["hi-en"] = model_name_or_path
    try:
        yield
    finally:
        config.MODELS["hi-en"] = original


def _load_dim1_scenarios(secret_filter: set[str] | None) -> list[dict]:
    records = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    if secret_filter is not None:
        records = [r for r in records if r["secret"] in secret_filter]
    return records


def dim1_for_secrets(secret_filter: set[str] | None) -> dict:
    scenarios = _load_dim1_scenarios(secret_filter)
    records = _resolve_actuals(scenarios, "hi-en")

    by_tier = {t: [r for r in records if r["tier"] == t] for t in ("near", "mid", "far")}
    band_accuracy = {
        "overall": _band_accuracy(records),
        "near": _band_accuracy(by_tier["near"]),
        "mid": _band_accuracy(by_tier["mid"]),
        "far": _band_accuracy(by_tier["far"]),
    }
    translation = [r for r in by_tier["near"] if r.get("subtype") == "translation"]
    associate = [r for r in by_tier["near"] if r.get("subtype") == "associate"]
    near_split = {
        "translation": {"n": len(translation), "band_accuracy": _band_accuracy(translation)},
        "associate": {"n": len(associate), "band_accuracy": _band_accuracy(associate)},
    }
    valid = [r for r in records if r["actual_rank"] is not None]
    expected_ordinals = [_TIER_ORDINAL[r["tier"]] for r in valid]
    actual_ranks = [r["actual_rank"] for r in valid]
    correlation = spearman_correlation(expected_ordinals, actual_ranks)
    monotonicity = _monotonicity(records)

    return {
        "n_secrets": len({r["secret"] for r in scenarios}),
        "n_scenarios": len(records),
        "band_accuracy": band_accuracy,
        "near_split_translation_vs_associate": near_split,
        "spearman_correlation": correlation,
        "monotonicity": monotonicity,
        "records": records,
    }


def dim2_for_pairs(pairs: list[tuple[str, str]]) -> dict:
    hien_vocab = load_hien_vocab()
    hien_matrix = embed_vocab(hien_vocab, "hi-en")
    hien_idx = {w: i for i, w in enumerate(hien_vocab)}
    n = len(hien_vocab)

    records: list[dict] = []
    for en_secret, hien_secret in pairs:
        if hien_secret not in hien_idx or en_secret not in hien_idx:
            records.append(
                {
                    "en_secret": en_secret,
                    "hien_secret": hien_secret,
                    "rank": None,
                    "band": None,
                    "consistent": None,
                    "resolution_error": "secret or translation missing from hi-en vocab",
                }
            )
            continue
        sims = cosine_similarities(hien_matrix, hien_matrix[hien_idx[hien_secret]])
        order = np.argsort(-sims)
        ranks = np.empty(n, dtype=np.int32)
        for rank_minus1, idx in enumerate(order):
            ranks[idx] = rank_minus1 + 1
        rank = int(ranks[hien_idx[en_secret]])
        band = band_for_rank(rank, n)
        records.append(
            {
                "en_secret": en_secret,
                "hien_secret": hien_secret,
                "rank": rank,
                "rank_percentile": round(100 * rank / n, 2),
                "band": band,
                "consistent": band in _GOOD_BANDS,
                "resolution_error": None,
            }
        )

    resolved = [r for r in records if r["resolution_error"] is None]
    consistent = [r for r in resolved if r["consistent"]]
    pass_rate = len(consistent) / len(resolved) if resolved else None
    ranks = [r["rank"] for r in resolved]

    return {
        "n_pairs": len(pairs),
        "n_resolved": len(resolved),
        "pass_rate_scorching_or_hot": pass_rate,
        "median_rank": float(np.median(ranks)) if ranks else None,
        "median_rank_percentile": float(np.median([r["rank_percentile"] for r in resolved]))
        if resolved
        else None,
        "records": records,
    }


def evaluate_model(model_name_or_path: str) -> dict:
    """Full held-out + dev + residual-weak evaluation for one hi-en model."""
    split = load_split()
    dev_secrets = set(split["dev_secrets"])
    test_secrets = set(split["test_secrets"])
    forced_weak = set(FORCED_TEST_SECRETS)

    daily_pairs = load_daily_pairs()
    dev_pairs = [(en, hien) for en, hien in daily_pairs if hien in dev_secrets]
    test_pairs = [(en, hien) for en, hien in daily_pairs if hien in test_secrets]
    weak_pairs = [(en, hien) for en, hien in daily_pairs if hien in forced_weak]

    with _model_override(model_name_or_path):
        result = {
            "model": model_name_or_path,
            "dim1_dev": dim1_for_secrets(dev_secrets),
            "dim1_test": dim1_for_secrets(test_secrets),
            "dim2_dev": dim2_for_pairs(dev_pairs),
            "dim2_test": dim2_for_pairs(test_pairs),
            "residual_weak_dim1": dim1_for_secrets(forced_weak),
            "residual_weak_dim2": dim2_for_pairs(weak_pairs),
        }
    return result


if __name__ == "__main__":
    import sys

    model = sys.argv[1] if len(sys.argv) > 1 else OFF_THE_SHELF_MODEL
    out = evaluate_model(model)
    print(f"model: {model}")
    print(f"  dim1_test spearman: {out['dim1_test']['spearman_correlation']:.4f}")
    print(f"  dim1_test band_accuracy: {out['dim1_test']['band_accuracy']}")
    print(f"  dim2_test pass_rate: {out['dim2_test']['pass_rate_scorching_or_hot']}")
    residual_pass_rate = out["residual_weak_dim2"]["pass_rate_scorching_or_hot"]
    print(f"  residual_weak dim2 pass_rate: {residual_pass_rate}")
