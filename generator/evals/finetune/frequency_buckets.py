from __future__ import annotations

"""
Head/tail vocabulary-frequency bucketing (spec-model-excellence.md WORKSTREAM B
item 6 — "is quality frequency-dependent, and by how much").

The hi-en vocab (evals.harness.dimension1_ranking / vocab.load_hien_vocab, n=10,495)
is a UNION of two differently-sourced halves with no common frequency scale:

  - hinglish-sourced (~544 words, vocab/hinglish.txt via parse_hinglish_file):
    frequency is looked up via wordfreq.word_frequency(devanagari_form, "hi"),
    using the pre-existing full-vocab transliteration table
    (data/devanagari_front_end_vocab_table.json — NOT regenerated here).
  - english-sourced (~9,951 words, vocab/en.txt): en.txt is ALREADY
    wordfreq-frequency-ordered (see vocab.py's module docstring/
    derive_en_vocab's "preserve that ordering" comment — most common first),
    so 1-based list position IS the frequency rank; no wordfreq call needed.

Because these two frequency scales are not directly comparable (English rank
position vs. a Hindi corpus frequency VALUE), each origin is bucketed into
head/mid/tail INDEPENDENTLY (tertiles within its own origin's population),
then reported both split-by-origin and collapsed into a combined head/mid/tail
(each origin's own top third counts as "head", etc.) — see bucket_report()'s
docstring for exactly what the combined view means.

TERTILES, not quartiles: the spec's item 6 asks for "head/mid/tail" (3 named
buckets) and offers quartiles as one option among several ("or another
sensible scheme — your call, document the cutoffs"). Quartiles produce 4
groups, which doesn't map onto 3 labels without an arbitrary merge, so this
module uses tertiles (3 equal-sized groups) directly — documented here as
the chosen scheme per the spec's own invitation to pick and document one.

Coverage honesty (no silent caps): a hinglish-sourced word's wordfreq lookup
can come back 0.0 for two indistinguishable reasons — genuinely absent from
wordfreq's Hindi corpus, or a garbage/low-quality transliteration in the
pre-existing table (spot-checked; e.g. "bachpan" -> "पवरा तिं", plainly
wrong). A handful of words are also missing a Devanagari form entirely (the
front-end build recorded an explicit `null` rather than fabricating one —
see build_devanagari_front_end.py's module docstring). Both cases are
reported as a separate "unresolved" bucket, never silently folded into
"tail".
"""

import json
import math
from pathlib import Path

from profanity import load_en_profanity, load_hi_profanity
from vocab import load_hien_vocab, parse_hinglish_file

DATA_DIR = Path(__file__).parent / "data"
DEVANAGARI_TABLE_PATH = DATA_DIR / "devanagari_front_end_vocab_table.json"

BucketName = str  # "head" | "mid" | "tail" | "unresolved"


# ---------------------------------------------------------------------------
# Pure functions — vocab-origin reconstruction + bucket assignment.
# No file I/O beyond what's already required to mirror vocab.py's own
# loaders; every function here is independently unit-testable with
# hand-built inputs (see tests/test_failure_taxonomy.py).
# ---------------------------------------------------------------------------


def hinglish_sourced_words(
    path: Path | None = None, combined_profanity: frozenset[str] | None = None
) -> list[str]:
    """Reconstruct exactly which words in load_hien_vocab() came from
    hinglish.txt (as opposed to the top-N English fill) — mirrors
    load_hien_vocab()'s own dedup/profanity filtering for the Hinglish half
    ONLY (see vocab.py's load_hien_vocab, which applies this identical
    filter before combining with the English half). Order preserved
    (first-occurrence, same as the real loader).

    `path`/`combined_profanity` are injectable purely for unit testing
    (see tests/test_failure_taxonomy.py) — real callers pass neither and
    get the real vocab/hinglish.txt + real profanity blocklists.
    """
    if combined_profanity is None:
        combined_profanity = load_en_profanity() | load_hi_profanity()

    hi_pairs = parse_hinglish_file(path)
    seen: set[str] = set()
    words: list[str] = []
    for w, _ in hi_pairs:
        if w not in combined_profanity and w not in seen:
            words.append(w)
            seen.add(w)
    return words


def hien_vocab_origin(vocab: list[str], hinglish_words: list[str]) -> dict[str, str]:
    """{word: "hinglish"|"english"} for every word in `vocab` (the combined
    hi-en vocab), given the reconstructed hinglish-sourced subset. Any word
    in `vocab` not in `hinglish_words` is english-sourced (load_hien_vocab's
    only other source)."""
    hi_set = set(hinglish_words)
    return {w: ("hinglish" if w in hi_set else "english") for w in vocab}


def english_rank_map(en_vocab: list[str]) -> dict[str, int]:
    """{word: 1-based frequency rank} from an already frequency-ordered
    English vocab list (vocab.load_en_vocab() / en.txt — most common
    first, see this module's docstring)."""
    return {w: i + 1 for i, w in enumerate(en_vocab)}


def tertile_bucket(rank: int, n: int) -> BucketName:
    """rank: 1-based position (1 = most frequent) out of n items in its
    population. Splits into 3 equal-sized groups by rank (ceil-based
    integer cutoffs, so n=1 unambiguously falls in "head" rather than an
    artifact of float-boundary rounding); the first third (lowest rank
    numbers = most frequent) is "head", the last third is "tail". n must
    be >= 1 and 1 <= rank <= n."""
    if n <= 0 or not (1 <= rank <= n):
        raise ValueError(f"rank={rank} out of bounds for n={n}")
    cutoff1 = math.ceil(n / 3)
    cutoff2 = math.ceil(2 * n / 3)
    if rank <= cutoff1:
        return "head"
    if rank <= cutoff2:
        return "mid"
    return "tail"


def load_devanagari_table() -> dict[str, str | None]:
    """Read the pre-existing full-vocab transliteration table — never
    regenerated here (build_devanagari_front_end.py is a separate,
    dedicated GCP-session artifact builder)."""
    return json.loads(DEVANAGARI_TABLE_PATH.read_text(encoding="utf-8"))


def hinglish_word_frequencies(
    words: list[str], deva_table: dict[str, str | None]
) -> dict[str, float | None]:
    """{word: wordfreq.word_frequency(devanagari_form, "hi")} for each
    hinglish-sourced word, or None if the word has no Devanagari form in
    `deva_table` at all (missing key or explicit null). A resolved 0.0
    frequency is returned as 0.0 (not None) — callers distinguish
    "no transliteration" (None) from "transliterated but wordfreq returned
    zero" (0.0) only for logging; both route to the "unresolved" bucket in
    build_word_bucket_table (see that function's docstring)."""
    from wordfreq import word_frequency  # local import — mirrors vocab.py's own pattern

    out: dict[str, float | None] = {}
    for w in words:
        deva = deva_table.get(w)
        out[w] = word_frequency(deva, "hi") if deva else None
    return out


def build_word_bucket_table() -> dict[str, dict]:
    """Full I/O-driving pipeline: for every word in the hi-en vocab, assign
    {"origin": "hinglish"|"english", "bucket": "head"|"mid"|"tail"|"unresolved",
    "frequency_rank_or_value": <int|float|None>}. Tertile buckets are computed
    SEPARATELY within each origin's population (see module docstring)."""
    vocab = load_hien_vocab()
    hi_words = hinglish_sourced_words()
    origin = hien_vocab_origin(vocab, hi_words)

    # IMPORTANT: rank english-sourced words within the population that's
    # ACTUALLY in the hi-en vocab (~9,951 words), NOT the full 55,000-word
    # en.txt -- load_hien_vocab only pulls the top HIEN_EN_TOP_N=10,000 of
    # en.txt (see vocab.py's _filter_en_for_hien), so ranking against the
    # full 55k population would put nearly every included word in "head" by
    # construction (a real bug this module hit and fixed: bucketing against
    # en.txt directly put 365/379 dim1 records in "head", including far-tier
    # decoy words that should span the WHOLE frequency range). `vocab`
    # already preserves en.txt's relative frequency order for its english
    # segment (load_hien_vocab appends _filter_en_for_hien's output, itself
    # an in-order en.txt subsequence), so filtering `vocab` for
    # origin=="english" recovers the correctly-scoped, correctly-ordered
    # population directly -- no need to touch load_en_vocab() at all here.
    en_words_in_vocab = [w for w in vocab if origin[w] == "english"]
    en_rank = english_rank_map(en_words_in_vocab)
    n_en = len(en_words_in_vocab)

    deva_table = load_devanagari_table()
    hi_freq = hinglish_word_frequencies(hi_words, deva_table)
    # Tertile ranks for hinglish words: rank 1 = highest wordfreq value,
    # computed only over the RESOLVED (non-None, non-zero) subset — an
    # unresolved word has no meaningful frequency to rank.
    resolved_hi = sorted(
        (w for w in hi_words if hi_freq.get(w) not in (None, 0.0)),
        key=lambda w: -hi_freq[w],
    )
    hi_rank = {w: i + 1 for i, w in enumerate(resolved_hi)}
    n_hi_resolved = len(resolved_hi)

    table: dict[str, dict] = {}
    for w in vocab:
        if origin[w] == "english":
            rank = en_rank.get(w)
            bucket = tertile_bucket(rank, n_en) if rank is not None else "unresolved"
            table[w] = {"origin": "english", "bucket": bucket, "frequency_rank_or_value": rank}
        else:
            freq = hi_freq.get(w)
            bucket = tertile_bucket(hi_rank[w], n_hi_resolved) if w in hi_rank else "unresolved"
            table[w] = {"origin": "hinglish", "bucket": bucket, "frequency_rank_or_value": freq}
    return table


def unresolved_coverage_stats(table: dict[str, dict], hi_words: list[str]) -> dict:
    """Honest coverage report for the hinglish-sourced half — what fraction
    of the 544 hinglish words fall into 'unresolved' and why (per this
    project's no-silent-caps documentation norm)."""
    hi_entries = {w: table[w] for w in hi_words if w in table}
    unresolved = [w for w, v in hi_entries.items() if v["bucket"] == "unresolved"]
    return {
        "n_hinglish_words": len(hi_entries),
        "n_unresolved": len(unresolved),
        "pct_unresolved": (len(unresolved) / len(hi_entries)) if hi_entries else None,
        "unresolved_words": sorted(unresolved),
    }


def join_dim1_with_buckets(dim1_records: list[dict], bucket_table: dict[str, dict]) -> list[dict]:
    """Attach each record's `word` frequency bucket/origin — join key is
    `word` (the item being judged for relatedness), NOT `secret` (per spec
    item 6). Records whose word isn't in the bucket table (shouldn't happen
    for resolved dim1 records, since the word must be in the embedded
    vocab) are attached with bucket=None and flagged."""
    out: list[dict] = []
    for r in dim1_records:
        info = bucket_table.get(r["word"])
        joined = dict(r)
        joined["freq_origin"] = info["origin"] if info else None
        joined["freq_bucket"] = info["bucket"] if info else None
        out.append(joined)
    return out


def bucket_report(joined_records: list[dict], vocab_size: int) -> dict:
    """Per (origin, bucket) and per combined-bucket: n, in_expected_band
    rate, mean rank percentile (actual_rank / vocab_size, lower = closer to
    the secret / better). Only records with a resolved actual_rank are
    counted. Combined buckets union english+hinglish head/mid/tail (each
    origin's own top/middle/bottom third) plus a combined "unresolved".
    """
    resolved = [r for r in joined_records if r["actual_rank"] is not None and r["freq_bucket"]]

    def _agg(records: list[dict]) -> dict:
        if not records:
            return {"n": 0, "in_expected_band_rate": None, "mean_rank_percentile": None}
        n = len(records)
        band_rate = sum(1 for r in records if r["in_expected_band"]) / n
        rank_pct = sum(r["actual_rank"] / vocab_size for r in records) / n
        return {"n": n, "in_expected_band_rate": band_rate, "mean_rank_percentile": rank_pct}

    by_origin_bucket: dict[str, dict] = {}
    for origin in ("english", "hinglish"):
        for bucket in ("head", "mid", "tail", "unresolved"):
            key = f"{origin}_{bucket}"
            subset = [
                r for r in resolved if r["freq_origin"] == origin and r["freq_bucket"] == bucket
            ]
            by_origin_bucket[key] = _agg(subset)

    combined: dict[str, dict] = {}
    for bucket in ("head", "mid", "tail", "unresolved"):
        subset = [r for r in resolved if r["freq_bucket"] == bucket]
        combined[bucket] = _agg(subset)

    head_rate = combined["head"]["in_expected_band_rate"]
    tail_rate = combined["tail"]["in_expected_band_rate"]
    tail_penalty = (
        head_rate - tail_rate if head_rate is not None and tail_rate is not None else None
    )

    return {
        "by_origin_bucket": by_origin_bucket,
        "combined": combined,
        "tail_penalty_head_minus_tail_rate": tail_penalty,
        "n_records_resolved": len(resolved),
        "n_records_total": len(joined_records),
    }


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    hi_words = hinglish_sourced_words()
    table = build_word_bucket_table()
    coverage = unresolved_coverage_stats(table, hi_words)
    print(
        f"hinglish-sourced: {coverage['n_hinglish_words']}, unresolved: "
        f"{coverage['n_unresolved']} ({coverage['pct_unresolved']:.1%})"
    )
    print(f"total vocab: {len(load_hien_vocab())}, table entries: {len(table)}")
