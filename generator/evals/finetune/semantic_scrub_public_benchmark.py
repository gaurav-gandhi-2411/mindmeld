from __future__ import annotations

"""
Semantic-proximity scrub for the public romanized-Hinglish relatedness
benchmark (evals/finetune/data/public_benchmark_staging/*.json).

`scrub_public_benchmark.py` catches STRING/morphological collisions (a
benchmark word literally IS or contains a live secret/alias). It cannot
catch a DIFFERENT leak: a benchmark word that is a strong SEMANTIC
associate of a live secret without sharing any string overlap at all (e.g.
a benchmark "ocean"-adjacent word, where a live pack secret genuinely IS
"ocean" -- a player who saw the benchmark word would get real information
about that live secret's neighborhood, even though no string matched).

Method: reuses the EXACT production rank/band machinery a real payload
build uses (embeddings.embed_vocab + rival.band_for_rank, both already
used by evals/harness/dimension1_ranking.py's `_resolve_actuals`) --
not a new/arbitrary cosine threshold. For every live secret (daily-
schedule + every pack, per language), compute its full-vocab rank table
once (cached after first embed), then look up the rank/band of every
distinct in-vocab benchmark word (same language) against that secret.

Severity mirrors the game's own band semantics, not an invented cutoff:
  - BLOCKING: band 0/1/2 (win/scorching/hot) -- the same band range the
    benchmark's own "near" tier targets (expected_bands [1,2]). A
    benchmark word landing this close to a LIVE secret it isn't supposed
    to be associated with discloses real information about that secret's
    neighborhood.
  - ADVISORY: band 3 (warm) -- the benchmark's own "mid" tier range;
    moderate proximity, reported for transparency, does not block.
  - Bands 4/5 (cold/freezing) are not reported at all -- by definition
    "not meaningfully related," which is the expected/safe case for
    nearly every (benchmark word, live secret) pair.

A benchmark word's own secret is excluded from its own check (a word is
SUPPOSED to be near/mid/far from its own secret -- that's the benchmark
itself, not a leak). Only cross-secret proximity to OTHER (live) secrets
is checked.

Run (from generator/):
    uv run python -m evals.finetune.semantic_scrub_public_benchmark
Exits non-zero (and prints every BLOCKING hit) on any hit; exits 0 on a
clean pass (printing exact counts checked plus the advisory list).
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from embeddings import cosine_similarities, embed_vocab
from packs import load_pack_secrets, load_packs_meta
from rival import band_for_rank
from schedule import load_schedule
from vocab import load_en_vocab, load_hien_vocab

STAGING_DIR = Path(__file__).parent / "data" / "public_benchmark_staging"
DIM1_EN_PATH = STAGING_DIR / "dim1_en.json"
DIM1_HIEN_PATH = STAGING_DIR / "dim1_hien.json"
DIM2_PAIRS_PATH = STAGING_DIR / "dim2_pairs.json"

_VOCAB_LOADERS = {"en": load_en_vocab, "hi-en": load_hien_vocab}
_BLOCKING_BANDS = {0, 1, 2}  # win / scorching / hot -- matches the benchmark's own "near" range
_ADVISORY_BANDS = {3}  # warm -- matches the benchmark's own "mid" range


@dataclass(frozen=True)
class Hit:
    benchmark_word: str
    benchmark_secret: str
    live_secret: str
    live_source: str
    lang: str
    rank: int
    band: int
    severity: str


def _live_secrets_by_lang() -> dict[str, list[tuple[str, str]]]:
    """lang -> [(secret, source)], canonical secrets only (aliases resolve to
    the same embedding/meaning as their canonical secret, so checking the
    canonical form covers the semantic space; string-alias coverage is
    scrub_public_benchmark.py's job)."""
    out: dict[str, list[tuple[str, str]]] = {"en": [], "hi-en": []}
    for lang in ("en", "hi-en"):
        for secret in load_schedule(lang):
            out[lang].append((secret, f"schedule:{lang}"))
    for pack in load_packs_meta():
        for lang in pack.langs:
            for secret in load_pack_secrets(pack, lang):
                out[lang].append((secret, f"pack:{pack.id}:{lang}"))
    return out


def _benchmark_words_by_lang() -> dict[str, list[tuple[str, str]]]:
    """lang -> [(word, owning_secret)] for every distinct (word, secret) in
    the finalized staging files, per language. `word` includes the
    secret itself (secret vs secret proximity is skipped at compare time)."""
    dim1_en = json.loads(DIM1_EN_PATH.read_text(encoding="utf-8"))
    dim1_hien = json.loads(DIM1_HIEN_PATH.read_text(encoding="utf-8"))
    dim2 = json.loads(DIM2_PAIRS_PATH.read_text(encoding="utf-8"))

    en_pairs: set[tuple[str, str]] = set()
    hien_pairs: set[tuple[str, str]] = set()

    for rec in dim1_en:
        en_pairs.add((rec["word"], rec["secret"]))
    for rec in dim1_hien:
        hien_pairs.add((rec["word"], rec["secret"]))
    for rec in dim2:
        hien_pairs.add((rec["hien_secret"], rec["hien_secret"]))
        en_pairs.add((rec["en_gloss"], rec["hien_secret"]))

    return {"en": sorted(en_pairs), "hi-en": sorted(hien_pairs)}


def find_semantic_hits() -> list[Hit]:
    live_by_lang = _live_secrets_by_lang()
    bench_by_lang = _benchmark_words_by_lang()
    hits: list[Hit] = []

    for lang in ("en", "hi-en"):
        vocab = _VOCAB_LOADERS[lang]()
        word_to_idx = {w: i for i, w in enumerate(vocab)}
        matrix = embed_vocab(vocab, lang, show_progress=False)
        n = len(vocab)

        bench_words = [(w, s) for w, s in bench_by_lang[lang] if w in word_to_idx]

        seen_live_secrets: set[str] = set()
        for live_secret, source in live_by_lang[lang]:
            if live_secret in seen_live_secrets:
                continue
            seen_live_secrets.add(live_secret)
            if live_secret not in word_to_idx:
                continue  # live secret not embeddable in this vocab -- nothing to compare
            sims = cosine_similarities(matrix, matrix[word_to_idx[live_secret]])
            order = sims.argsort()[::-1]
            ranks = {}
            for rank_minus1, idx in enumerate(order):
                ranks[idx] = rank_minus1 + 1

            for word, owning_secret in bench_words:
                if word == live_secret or owning_secret == live_secret:
                    continue  # a word's proximity to its OWN secret is the benchmark, not a leak
                rank = ranks[word_to_idx[word]]
                band = band_for_rank(rank, n)
                if band in _BLOCKING_BANDS:
                    hits.append(
                        Hit(word, owning_secret, live_secret, source, lang, rank, band, "blocking")
                    )
                elif band in _ADVISORY_BANDS:
                    hits.append(
                        Hit(word, owning_secret, live_secret, source, lang, rank, band, "advisory")
                    )

    return hits


def run_scrub() -> dict:
    hits = find_semantic_hits()
    blocking = [h for h in hits if h.severity == "blocking"]
    advisory = [h for h in hits if h.severity == "advisory"]
    bench_by_lang = _benchmark_words_by_lang()
    live_by_lang = _live_secrets_by_lang()
    return {
        "n_benchmark_words_checked": sum(len(v) for v in bench_by_lang.values()),
        "n_live_secrets_checked": sum(len({s for s, _ in v}) for v in live_by_lang.values()),
        "n_blocking": len(blocking),
        "n_advisory": len(advisory),
        "blocking_hits": blocking,
        "advisory_hits": advisory,
        "passed": len(blocking) == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    result = run_scrub()
    print(
        f"semantic scrub: {result['n_benchmark_words_checked']} benchmark (word,secret) pairs "
        f"checked against {result['n_live_secrets_checked']} distinct live secrets (en + hi-en)"
    )
    if result["advisory_hits"]:
        print(f"  {len(result['advisory_hits'])} ADVISORY (band=warm) hit(s):")
        for h in result["advisory_hits"]:
            print(
                f"    [{h.lang}] '{h.benchmark_word}' (benchmark secret={h.benchmark_secret}) "
                f"<-> live '{h.live_secret}' ({h.live_source}) rank={h.rank} band={h.band}"
            )
    if not result["passed"]:
        print(f"SEMANTIC SCRUB FAILED -- {result['n_blocking']} BLOCKING hit(s):")
        for h in result["blocking_hits"]:
            print(
                f"  [{h.lang}] '{h.benchmark_word}' (benchmark secret={h.benchmark_secret}) "
                f"<-> live '{h.live_secret}' ({h.live_source}) rank={h.rank} band={h.band}"
            )
        sys.exit(1)
    print(
        f"semantic scrub OK: 0 blocking (near-band) hits between the public benchmark and "
        f"live game secrets ({result['n_advisory']} advisory/warm-band hits reported above)"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
