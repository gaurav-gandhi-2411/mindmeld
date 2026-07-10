from __future__ import annotations

"""
Dimension 1 — semantic ranking quality.

Loads the synthetic near/mid/far scenarios (evals/gen_dim1_scenarios.py),
embeds the FULL vocab for the language (cache hit if a prior build already
ran — see embeddings.embed_vocab), computes each scenario word's actual rank
+ band relative to its secret (identical logic to payload._build_payload_core,
so this measures exactly what players experience), and reports:

  - band-accuracy: overall, per tier, and (hi-en only) near-tier split by
    subtype (translation vs in-language associate — GG review, 2026-07-10:
    these test different capabilities and must not be blended).
  - Spearman rank correlation between expected closeness (near=1, mid=2,
    far=3) and actual rank, pooled across all scenarios for the language.
  - monotonicity violation rate: fraction of (closer-tier, farther-tier)
    word pairs, within the same secret, where the closer-tier word did NOT
    actually rank better.
"""

import json
from pathlib import Path

import numpy as np

from embeddings import cosine_similarities, embed_vocab
from evals.harness.metrics import spearman_correlation
from rival import band_for_rank
from vocab import load_en_vocab, load_hien_vocab

SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"

_TIER_ORDINAL = {"near": 1, "mid": 2, "far": 3}

_VOCAB_LOADERS = {"en": load_en_vocab, "hi-en": load_hien_vocab}


def _load_scenarios(lang: str) -> list[dict]:
    fname = "dim1_en.json" if lang == "en" else "dim1_hien.json"
    path = SCENARIOS_DIR / fname
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_actuals(scenarios: list[dict], lang: str) -> list[dict]:
    """Attach actual_rank/actual_band to every scenario record.

    Embeds the full vocab once (cached after first run — see
    embeddings.embed_vocab's file-based cache), then for each distinct
    secret in the scenario set computes the full cosine-similarity/rank
    table once and looks up every scenario word's rank in it — identical
    computation to what a real payload build does for that secret.
    """
    vocab = _VOCAB_LOADERS[lang]()
    matrix = embed_vocab(vocab, lang)
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    n = len(vocab)

    secrets = sorted({s["secret"] for s in scenarios})
    rank_tables: dict[str, np.ndarray] = {}
    for secret in secrets:
        if secret not in word_to_idx:
            continue
        sims = cosine_similarities(matrix, matrix[word_to_idx[secret]])
        order = np.argsort(-sims)
        ranks = np.empty(n, dtype=np.int32)
        for rank_minus1, idx in enumerate(order):
            ranks[idx] = rank_minus1 + 1
        rank_tables[secret] = ranks

    resolved: list[dict] = []
    for rec in scenarios:
        secret, word = rec["secret"], rec["word"]
        out = dict(rec)
        if secret not in rank_tables or word not in word_to_idx:
            out["actual_rank"] = None
            out["actual_band"] = None
            out["in_expected_band"] = False
            out["resolution_error"] = f"secret={secret!r} or word={word!r} not in vocab"
        else:
            rank = int(rank_tables[secret][word_to_idx[word]])
            band = band_for_rank(rank, n)
            out["actual_rank"] = rank
            out["actual_band"] = band
            out["in_expected_band"] = band in rec["expected_bands"]
            out["resolution_error"] = None
        resolved.append(out)
    return resolved


def _band_accuracy(records: list[dict]) -> float | None:
    if not records:
        return None
    return sum(1 for r in records if r["in_expected_band"]) / len(records)


def _monotonicity(records: list[dict]) -> dict:
    """For each secret, every (closer-tier word, farther-tier word) pair must
    have closer.actual_rank < farther.actual_rank. Returns violation stats.
    """
    by_secret: dict[str, list[dict]] = {}
    for r in records:
        if r["actual_rank"] is None:
            continue
        by_secret.setdefault(r["secret"], []).append(r)

    total = 0
    violations = 0
    violation_examples: list[dict] = []
    for secret, recs in by_secret.items():
        by_tier: dict[str, list[dict]] = {"near": [], "mid": [], "far": []}
        for r in recs:
            by_tier[r["tier"]].append(r)
        tier_order = ["near", "mid", "far"]
        for i, closer_tier in enumerate(tier_order):
            for farther_tier in tier_order[i + 1 :]:
                for c in by_tier[closer_tier]:
                    for f in by_tier[farther_tier]:
                        total += 1
                        if not (c["actual_rank"] < f["actual_rank"]):
                            violations += 1
                            if len(violation_examples) < 20:
                                violation_examples.append(
                                    {
                                        "secret": secret,
                                        "closer": f"{c['word']} ({closer_tier}, "
                                        f"rank {c['actual_rank']})",
                                        "farther": f"{f['word']} ({farther_tier}, "
                                        f"rank {f['actual_rank']})",
                                    }
                                )
    return {
        "total_pairs": total,
        "violations": violations,
        "violation_rate": (violations / total) if total else None,
        "examples": violation_examples,
    }


def run_dimension1(lang: str) -> dict:
    """Compute all dimension-1 metrics for one language. Returns a report dict."""
    scenarios = _load_scenarios(lang)
    records = _resolve_actuals(scenarios, lang)

    by_tier = {
        tier: [r for r in records if r["tier"] == tier] for tier in ("near", "mid", "far")
    }

    band_accuracy = {
        "overall": _band_accuracy(records),
        "near": _band_accuracy(by_tier["near"]),
        "mid": _band_accuracy(by_tier["mid"]),
        "far": _band_accuracy(by_tier["far"]),
    }

    near_split = None
    if lang == "hi-en":
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

    flagged_weak = [
        {
            "secret": r["secret"],
            "word": r["word"],
            "tier": r["tier"],
            "subtype": r.get("subtype"),
            "expected_bands": r["expected_bands"],
            "actual_band": r["actual_band"],
            "actual_rank": r["actual_rank"],
            "note": r.get("note"),
        }
        for r in records
        if not r["in_expected_band"]
    ]

    resolution_errors = [r for r in records if r.get("resolution_error")]

    return {
        "lang": lang,
        "n_scenarios": len(records),
        "band_accuracy": band_accuracy,
        "band_accuracy_hien_near_split": near_split,
        "spearman_correlation": correlation,
        "monotonicity": monotonicity,
        "flagged_weak": flagged_weak,
        "resolution_errors": resolution_errors,
    }


if __name__ == "__main__":
    import sys

    for lang in ("en", "hi-en"):
        result = run_dimension1(lang)
        print(f"\n=== dimension 1 — {lang} ===")
        print(f"  n_scenarios: {result['n_scenarios']}")
        print(f"  band_accuracy: {result['band_accuracy']}")
        if result["band_accuracy_hien_near_split"]:
            print(f"  hi-en near split: {result['band_accuracy_hien_near_split']}")
        print(f"  spearman_correlation: {result['spearman_correlation']:.4f}")
        mono = result["monotonicity"]
        print(
            f"  monotonicity: {mono['violations']}/{mono['total_pairs']} violations "
            f"({mono['violation_rate']:.4f} rate)"
        )
        print(f"  flagged weak: {len(result['flagged_weak'])}")
        for w in result["flagged_weak"][:15]:
            print(
                f"    {w['secret']:12s} <- {w['word']:14s} [{w['tier']}/{w.get('subtype')}] "
                f"expected={w['expected_bands']} actual={w['actual_band']} "
                f"(rank {w['actual_rank']})"
            )
        if result["resolution_errors"]:
            print(f"  RESOLUTION ERRORS: {len(result['resolution_errors'])}", file=sys.stderr)
            for e in result["resolution_errors"]:
                print(f"    {e}", file=sys.stderr)
