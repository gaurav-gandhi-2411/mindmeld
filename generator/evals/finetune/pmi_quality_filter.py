from __future__ import annotations

"""
LLM-judge quality filter for corpus PMI-mined relatedness pairs
(data/raw/corpus_pmi_pairs.jsonl, produced by pmi_mine.py) — STAGING ONLY,
same status as pmi_mine.py: this module does not touch assemble_data.py or
any frozen training file.

Why this exists: a manual audit of the mined pairs found a 34.6% dict-vs-LLM
transliteration calibration agreement rate (see pmi_mine.py's calibration
output) and, more importantly, nonsense pairs SPREAD ACROSS THE FULL SCORE
RANGE, not clustered at the bottom — e.g. "kaam"<->"ui" (LLM hallucination,
score~0.56), "ek"<->"hazing" (dict-sourced garbled romanization, score~0.51),
"neeche"<->"subscribe" and "fielder"<->"honth" (real dict-sourced words with
spurious YouTube-comment-adjacent corpus co-occurrence, scores~0.76/0.80).
Because the noise sources are heterogeneous (transliteration garbling AND
spurious co-occurrence, both occurring at all score levels), a pure
score/PMI floor cannot cleanly separate good pairs from bad ones. This is the
same class of problem commit 694b2a0 already fixed once for a different
source in this pipeline (homograph collisions / fuzzy negatives) — the fix
here is the same shape: an independent semantic check, not a numeric
threshold.

Pattern: mirrors llm_augment.py's `quality_filter()` — an ISOLATED judge call
per candidate (not bundled with generation, so the model can't rubber-stamp
its own output), local Ollama qwen3:8b, $0. Isolation here means each pair is
judged on its own semantic merits within its batch prompt; unlike
llm_augment.py's per-triplet calls, judgments are BATCHED (pmi_mine.py's
report: batching ~25 items/call cut a full sweep from ~5hrs to ~20min) — each
call judges up to BATCH_SIZE pairs and returns a JSON array keyed by
batch-local index, matched back to pairs by index (not by content, so
duplicate (anchor, neighbor) pairs across the corpus never get misattributed
judgments from another instance).

Question asked per pair (see _JUDGE_PROMPT): is "neighbor" a genuine,
real-word semantic associate of "anchor" in Hinglish code-mixed conversation
— not a nonsense token, not a transliteration artifact, not a coincidental/
spurious pairing? Any pair the model doesn't return a judgment for (parse
failure, missing index, whole-batch Ollama error) is REJECTED, not accepted
— fail-closed, matching llm_augment.quality_filter's except-block behavior
of returning False rather than True on any I/O failure.

Run: uv run python -m evals.finetune.pmi_quality_filter
Input:  evals/finetune/data/raw/corpus_pmi_pairs.jsonl (gitignored staging)
Output: evals/finetune/data/raw/corpus_pmi_pairs_filtered.jsonl (gitignored
staging — still not wired into assemble_data.py by this module).
"""

import json
import logging
import random
from pathlib import Path

from evals.finetune.llm_augment import LLMUnavailableError, _call_ollama

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
RAW_DIR = DATA_DIR / "raw"
IN_PATH = RAW_DIR / "corpus_pmi_pairs.jsonl"
OUT_PATH = RAW_DIR / "corpus_pmi_pairs_filtered.jsonl"

BATCH_SIZE = 25
SEED = 42

# Reporting-only bands (not used for accept/reject) so the printed example
# set in __main__ demonstrably covers both ends of pmi_mine.py's documented
# SCORE_LO=0.45..SCORE_HI=0.80 output range, per the task's instruction to
# show low-band and high-band examples rather than trusting the filter blind.
LOW_BAND_MAX = 0.55
HIGH_BAND_MIN = 0.70

_JUDGE_BATCH_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "related_ok": {"type": "boolean"},
        },
        "required": ["index", "related_ok"],
    },
}

_JUDGE_PROMPT = """In Hindi-English (Hinglish) code-mixed conversation, judge each of the \
following {n} (anchor, neighbor) word pairs. For each pair: is "neighbor" a genuine, real-word \
semantic associate of "anchor" (same domain, commonly co-occurring in real use)? Answer \
strictly false if "neighbor" is not a real word you recognize, if the pairing looks like a \
transliteration artifact or garbled romanization, or if the connection seems forced or merely \
coincidental (spurious co-occurrence with no real semantic link).

Pairs:
{pairs_block}

Respond with ONLY a JSON array, no other text, no markdown fences, exactly one entry per pair \
by its index:
[{{"index": 0, "related_ok": <true|false>}}, ...]"""


# ---------------------------------------------------------------------------
# Pure logic (unit-testable without corpus file / Ollama / network)
# ---------------------------------------------------------------------------


def _chunks(items: list[dict], size: int) -> list[list[dict]]:
    """Split `items` into consecutive chunks of at most `size`, preserving order."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_pairs_block(batch: list[dict]) -> str:
    """
    Render a batch of {"anchor", "neighbor", ...} records as a numbered
    prompt block, 0-indexed to match the response schema's "index" field.
    """
    return "\n".join(
        f'{i}. anchor="{p["anchor"]}", neighbor="{p["neighbor"]}"' for i, p in enumerate(batch)
    )


def parse_judge_batch_response(raw: object, batch_size: int) -> dict[int, bool]:
    """
    Pure parsing of a judge batch call's response into {batch_local_index:
    related_ok}. Malformed entries (non-dict, non-int index, out-of-range
    index, non-bool verdict) are silently dropped rather than raising — a
    partially-malformed response should still yield judgments for the
    well-formed entries; callers treat any index missing from the returned
    dict as "no judgment" and reject it (fail-closed, see run_quality_filter).
    """
    if not isinstance(raw, list):
        return {}
    out: dict[int, bool] = {}
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        idx = rec.get("index")
        ok = rec.get("related_ok")
        if not isinstance(idx, int) or isinstance(idx, bool) or not isinstance(ok, bool):
            continue
        if not (0 <= idx < batch_size):
            continue
        out[idx] = ok
    return out


def stratified_examples(
    records: list[dict],
    n: int,
    low_max: float = LOW_BAND_MAX,
    high_min: float = HIGH_BAND_MIN,
    seed: int = SEED,
) -> list[dict]:
    """
    Pick up to `n` example records for human review, biased to include some
    from the low score band (score <= low_max) and some from the high score
    band (score >= high_min) rather than an unweighted random sample, which
    could easily miss one or both bands by chance on a small n. Remaining
    slots are filled randomly from the full record set (mid-band included).
    Deterministic (fixed seed) so report examples are reproducible run-to-run.
    """
    rng = random.Random(seed)
    low = [r for r in records if r["score"] <= low_max]
    high = [r for r in records if r["score"] >= high_min]

    quota = max(1, n // 3)
    picked: list[dict] = []
    picked_ids: set[int] = set()
    for band in (low, high):
        k = min(quota, len(band))
        for r in rng.sample(band, k):
            if id(r) not in picked_ids:
                picked.append(r)
                picked_ids.add(id(r))

    remaining_pool = [r for r in records if id(r) not in picked_ids]
    remaining_needed = max(0, n - len(picked))
    picked.extend(rng.sample(remaining_pool, min(remaining_needed, len(remaining_pool))))
    return picked[:n]


# ---------------------------------------------------------------------------
# I/O: Ollama batch calls
# ---------------------------------------------------------------------------


def judge_batch(batch: list[dict]) -> dict[int, bool]:
    """One batched Ollama call judging up to BATCH_SIZE pairs at once."""
    prompt = _JUDGE_PROMPT.format(n=len(batch), pairs_block=build_pairs_block(batch))
    try:
        raw = _call_ollama(prompt, response_format=_JUDGE_BATCH_SCHEMA)
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("quality-filter batch failed for %d pairs: %s", len(batch), e)
        return {}
    return parse_judge_batch_response(raw, len(batch))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_quality_filter(
    pairs: list[dict], batch_size: int = BATCH_SIZE
) -> tuple[list[dict], list[dict], dict]:
    """
    Judge every pair in `pairs` via batched Ollama calls. Returns
    (accepted, rejected, stats). Any pair whose batch produced no judgment
    for its index (whole-batch failure or malformed per-item response) is
    rejected — fail-closed.
    """
    accepted: list[dict] = []
    rejected: list[dict] = []
    n_no_judgment = 0
    for batch in _chunks(pairs, batch_size):
        judgments = judge_batch(batch)
        for i, pair in enumerate(batch):
            verdict = judgments.get(i)
            if verdict is None:
                n_no_judgment += 1
                verdict = False
            (accepted if verdict else rejected).append(pair)

    stats = {
        "n_input": len(pairs),
        "n_accepted": len(accepted),
        "n_rejected": len(rejected),
        "n_no_judgment_fail_closed": n_no_judgment,
    }
    return accepted, rejected, stats


def load_pairs(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build() -> tuple[dict, list[dict], list[dict]]:
    pairs = load_pairs(IN_PATH)
    print(f"Loaded {len(pairs):,} candidate pairs from {IN_PATH}")

    accepted, rejected, stats = run_quality_filter(pairs)
    print(f"  {json.dumps(stats)}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in accepted:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats["output_path"] = str(OUT_PATH)
    return stats, accepted, rejected


_KNOWN_BAD_PAIRS = (
    ("kaam", "ui"),
    ("ek", "hazing"),
    ("neeche", "subscribe"),
    ("fielder", "honth"),
    ("kangan", "apanee"),
    ("railway", "tika"),
)


if __name__ == "__main__":
    result_stats, result_accepted, result_rejected = build()
    print(json.dumps(result_stats, indent=2))

    print("\n=== 15 REJECTED examples (stratified low/high score band) ===")
    for r in stratified_examples(result_rejected, 15):
        print(f"  REJECT  {r['anchor']!r} <-> {r['neighbor']!r}  score={r['score']:.3f}")

    print("\n=== 15 ACCEPTED examples (stratified low/high score band) ===")
    for r in stratified_examples(result_accepted, 15):
        print(f"  ACCEPT  {r['anchor']!r} <-> {r['neighbor']!r}  score={r['score']:.3f}")

    print("\n=== Known-bad pair check ===")
    accepted_set = {(r["anchor"], r["neighbor"]) for r in result_accepted}
    any_survived = False
    for anchor, neighbor in _KNOWN_BAD_PAIRS:
        survived = (anchor, neighbor) in accepted_set
        if survived:
            any_survived = True
        status = "SURVIVED FILTER (BAD)" if survived else "correctly rejected"
        print(f"  {anchor!r} <-> {neighbor!r}: {status}")
    if any_survived:
        print("\n  *** WARNING: at least one known-bad pair survived the quality filter ***")
    else:
        print("\n  all 6 known-bad pairs correctly rejected")
