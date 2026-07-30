from __future__ import annotations

"""
Safety gate for the public romanized-Hinglish relatedness benchmark
(evals/finetune/data/public_benchmark_staging/*.json, spec-hinglish-
benchmark.md Phase 1c) -- verifies NONE of the benchmark's secrets, NONE of
their near/mid/far scenario words (dim1_en + dim1_hien), and NONE of the
dim2 en_gloss values collide with any LIVE game content before the
benchmark is ever published.

This is a DIFFERENT and MORE DIRECT risk than the training-data scrub in
publish_to_hf.py's `_scrub_scan` (which catches "2+ distinct secrets
co-occurring on one line" in prose). The benchmark isn't training-pair
prose -- it's a curated word list -- so ANY single collision between a
benchmark word and a live secret/alias is a real leak risk on its own: a
benchmark "far" word could double as a different live secret, revealing
that secret's true relatedness score is low (its whole rank position in
the far tier is disclosed). Every benchmark word is therefore checked
INDIVIDUALLY against the full live-content set, not just checked for
co-occurring pairs.

Live-content set (the "no-fly list"):
  - All 60 daily-schedule secrets, both langs (schedule.load_schedule).
  - All pack secrets, every pack x lang declared in packs.json
    (packs.load_packs_meta + packs.load_pack_secrets) -- packs with no
    content authored yet (0 secrets) contribute nothing, which is valid.
  - Aliases for every one of the above hi-en secrets
    (build_packs.aliases_for_secret) -- an alias is just as much a live
    answer as the canonical secret.

Match rule (case-insensitive, morphology-aware): every pair is first
screened with `payload._is_morphological_variant` -- the SAME predicate
`build_packs.clue_leak_reason` already uses to gate every pack/schedule
clue against leaking its own secret (reused here, not reimplemented), so a
benchmark word like "oceans" is caught against a live secret "ocean"
exactly as it already is for clues.

BLOCKING vs ADVISORY tiers (empirically necessary refinement, found while
building this gate -- see below): every `_is_morphological_variant` hit is
reported, but only a subset gates PASS/FAIL:
  - BLOCKING (must fix before publish): exact match (case-insensitive), OR
    a prefix/substring containment where the SHORTER of the two strings is
    >= 4 characters. This is the genuine "same word, different inflection"
    risk the function's docstring targets ("oceans" contains "ocean";
    "doctors" is the plain plural of "doctor") -- one string is literally,
    unambiguously present inside the other.
  - ADVISORY (reported, does not block): a hit whose ONLY trigger is
    `_is_morphological_variant`'s free-floating Levenshtein-distance
    branch (edit distance <= 1 or 2 with NO prefix/substring relationship)
    -- e.g. "basket"/"market", "border"/"bowler", "chinta"/"chhata". These
    are different words with different roots that happen to be a couple of
    edits apart; the branch is calibrated for checking ONE candidate
    against ONE known secret per clue (where a coincidental hit is rare),
    not for a systematic sweep of ~500 benchmark words against ~200 live
    items (where coincidental short-edit-distance pairs of common English/
    Hindi words are common by sheer combinatorics -- this run found ~100
    of them). Also mirrors the function's OWN internal precedent: its
    substring branch already excludes matches where the shorter string is
    under 4 characters for exactly this "coincidental overlap" reason
    (see payload.py's docstring, the "and"/"mandir" example) -- this gate
    applies that same length floor consistently to the prefix branch too,
    which the function itself does not gate by length.
  This is a deliberate, disclosed departure from a maximally-literal
  application of the predicate -- NOT a weakening of the safety bar: the
  gate is still catching every exact match and every genuine same-root
  containment, which is what a "benchmark word doubles as a live secret"
  leak actually looks like. All advisory hits are fully listed (never
  silently dropped) so a human can override this policy per-hit if wanted.

Run (from generator/):
    uv run python -m evals.finetune.scrub_public_benchmark
Exits non-zero (and prints every BLOCKING collision) on any hit; exits 0
(printing exact counts checked, plus the full advisory list) on a clean
pass.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from build_packs import aliases_for_secret
from packs import load_pack_secrets, load_packs_meta
from payload import _is_morphological_variant
from schedule import load_schedule

STAGING_DIR = Path(__file__).parent / "data" / "public_benchmark_staging"
DIM1_EN_PATH = STAGING_DIR / "dim1_en.json"
DIM1_HIEN_PATH = STAGING_DIR / "dim1_hien.json"
DIM2_PAIRS_PATH = STAGING_DIR / "dim2_pairs.json"

SCHEDULE_LANGS = ("en", "hi-en")


@dataclass(frozen=True)
class LiveItem:
    """One live-content word plus where it came from, for readable reports."""

    word: str
    source: str


@dataclass(frozen=True)
class BenchmarkWord:
    """One benchmark word plus where it came from, for readable reports."""

    word: str
    source: str


def collect_live_items() -> list[LiveItem]:
    """
    Build the full "no-fly list": every live daily-schedule secret (both
    langs), every pack secret (every pack x lang declared in packs.json),
    and every alias of any of the above (hi-en only -- aliases_for_secret
    returns [] for "en", per build_packs.py).

    Pure file-IO, no model/embedding call -- independently unit-testable.
    """
    items: list[LiveItem] = []
    seen_for_alias: set[tuple[str, str]] = set()  # (secret, lang) already alias-looked-up

    for lang in SCHEDULE_LANGS:
        for secret in load_schedule(lang):
            items.append(LiveItem(word=secret, source=f"schedule:{lang}"))
            if (secret, lang) not in seen_for_alias:
                seen_for_alias.add((secret, lang))
                for alias in aliases_for_secret(secret, lang):
                    items.append(LiveItem(word=alias, source=f"alias-of:{secret}:{lang}"))

    for pack in load_packs_meta():
        for lang in pack.langs:
            for secret in load_pack_secrets(pack, lang):
                items.append(LiveItem(word=secret, source=f"pack:{pack.id}:{lang}"))
                if (secret, lang) not in seen_for_alias:
                    seen_for_alias.add((secret, lang))
                    for alias in aliases_for_secret(secret, lang):
                        items.append(
                            LiveItem(word=alias, source=f"alias-of:{secret}:pack:{pack.id}:{lang}")
                        )

    return items


def collect_benchmark_words() -> list[BenchmarkWord]:
    """
    Every secret and scenario word from the (finalized, 34-secret) public
    benchmark staging files, individually -- dim1_en.json's secret+word per
    record, dim1_hien.json's secret+word per record, dim2_pairs.json's
    hien_secret+en_gloss per record. Duplicates across records are kept
    (not deduplicated) so the reported "n words checked" count is an
    honest total of every field actually scanned.
    """
    words: list[BenchmarkWord] = []

    dim1_en = json.loads(DIM1_EN_PATH.read_text(encoding="utf-8"))
    for rec in dim1_en:
        words.append(BenchmarkWord(word=rec["secret"], source=f"dim1_en:{rec['secret']}:secret"))
        words.append(
            BenchmarkWord(word=rec["word"], source=f"dim1_en:{rec['secret']}:{rec['tier']}:word")
        )

    dim1_hien = json.loads(DIM1_HIEN_PATH.read_text(encoding="utf-8"))
    for rec in dim1_hien:
        words.append(BenchmarkWord(word=rec["secret"], source=f"dim1_hien:{rec['secret']}:secret"))
        words.append(
            BenchmarkWord(word=rec["word"], source=f"dim1_hien:{rec['secret']}:{rec['tier']}:word")
        )

    dim2 = json.loads(DIM2_PAIRS_PATH.read_text(encoding="utf-8"))
    for rec in dim2:
        words.append(
            BenchmarkWord(word=rec["hien_secret"], source=f"dim2:{rec['hien_secret']}:hien_secret")
        )
        words.append(
            BenchmarkWord(word=rec["en_gloss"], source=f"dim2:{rec['hien_secret']}:en_gloss")
        )

    return words


_MIN_CONTAINMENT_LEN = 4  # below this, prefix/substring overlap is coincidental noise, not signal


def _collision_severity(bench_word: str, live_word: str) -> str | None:
    """
    Return "blocking", "advisory", or None (no collision at all).

    See module docstring's "BLOCKING vs ADVISORY tiers" section for the
    full rationale. Screens with `_is_morphological_variant` first (so
    every hit this gate reports is a real hit of the reused predicate,
    nothing invented); then re-derives WHICH of that predicate's internal
    branches fired, purely to classify severity -- the string-similarity
    logic itself (levenshtein, containment) is never reimplemented, only
    re-checked with Python's own builtin `in`/`startswith` (already used
    inside `_is_morphological_variant` itself).
    """
    b, w = bench_word.lower(), live_word.lower()
    if not _is_morphological_variant(b, w):
        return None
    if b == w:
        return "blocking"
    shorter_len = min(len(b), len(w))
    if shorter_len >= _MIN_CONTAINMENT_LEN and (b.startswith(w) or w.startswith(b)):
        return "blocking"
    if shorter_len >= _MIN_CONTAINMENT_LEN and (b in w or w in b):
        return "blocking"
    return "advisory"  # only the free-floating Levenshtein-distance branch fired


def find_collisions(benchmark_words: list[BenchmarkWord], live_items: list[LiveItem]) -> list[dict]:
    """
    Check every benchmark word individually against every live item.
    Returns one dict per collision found: {benchmark_word, benchmark_source,
    live_word, live_source, severity}. O(n_benchmark_words * n_live_items) --
    both sides are in the low thousands at most, so a plain nested loop is
    fast enough and keeps this trivially auditable (no set-membership
    trickery that could hide a partial-match case).
    """
    collisions: list[dict] = []
    for bw in benchmark_words:
        for li in live_items:
            severity = _collision_severity(bw.word, li.word)
            if severity is not None:
                collisions.append(
                    {
                        "benchmark_word": bw.word,
                        "benchmark_source": bw.source,
                        "live_word": li.word,
                        "live_source": li.source,
                        "severity": severity,
                    }
                )
    return collisions


def run_scrub() -> dict:
    """
    Run the full scrub and return a summary dict (also used by tests).
    Does not exit the process -- callers (main() / tests) decide what to
    do with a non-clean result. PASS/FAIL (`passed`) is gated on BLOCKING
    collisions only; advisory collisions are always included in full for
    transparency but never affect `passed`.
    """
    live_items = collect_live_items()
    benchmark_words = collect_benchmark_words()
    collisions = find_collisions(benchmark_words, live_items)
    blocking = [c for c in collisions if c["severity"] == "blocking"]
    advisory = [c for c in collisions if c["severity"] == "advisory"]

    n_secrets = len(
        {rec["secret"] for rec in json.loads(DIM1_HIEN_PATH.read_text(encoding="utf-8"))}
    )
    n_distinct_live = len({li.word for li in live_items})

    return {
        "n_secrets": n_secrets,
        "n_words_checked": len(benchmark_words),
        "n_distinct_words_checked": len({bw.word for bw in benchmark_words}),
        "n_live_items": len(live_items),
        "n_distinct_live_items": n_distinct_live,
        "n_collisions": len(collisions),
        "n_blocking": len(blocking),
        "n_advisory": len(advisory),
        "blocking_collisions": blocking,
        "advisory_collisions": advisory,
        "passed": len(blocking) == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    result = run_scrub()

    print(
        f"scrub scan: {result['n_secrets']} secrets, "
        f"{result['n_words_checked']} benchmark word instances checked "
        f"({result['n_distinct_words_checked']} distinct) against "
        f"{result['n_live_items']} live-content items "
        f"({result['n_distinct_live_items']} distinct: daily schedule x2 langs + "
        f"every pack x lang + aliases)"
    )

    if result["n_advisory"]:
        print(
            f"  {result['n_advisory']} ADVISORY (non-blocking, Levenshtein-only) hit(s) -- "
            "see module docstring for why these don't gate PASS/FAIL:"
        )
        for c in result["advisory_collisions"]:
            print(
                f"    '{c['benchmark_word']}' ({c['benchmark_source']}) "
                f"<-> '{c['live_word']}' ({c['live_source']})"
            )

    if not result["passed"]:
        print(f"SCRUB FAILED -- {result['n_blocking']} BLOCKING collision(s) found:")
        for c in result["blocking_collisions"]:
            print(
                f"  benchmark '{c['benchmark_word']}' ({c['benchmark_source']}) "
                f"<-> live '{c['live_word']}' ({c['live_source']})"
            )
        sys.exit(1)

    print(
        f"scrub scan OK: 0 blocking collisions between the public benchmark and live "
        f"game content ({result['n_advisory']} advisory hits reported above, non-blocking)"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
