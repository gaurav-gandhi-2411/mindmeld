from __future__ import annotations

"""
Full error taxonomy over the shipped model's failing dim1 pairs
(spec-model-excellence.md WORKSTREAM B item 5).

Classifies every record with `in_expected_band == False` in the shipped
checkpoint (evals/finetune/data/bakeoff_raw/
gauravgandhi2411__hinglish-relatedness-sbert.json's `dim1_records`, 124 of
379) into exactly one of six categories, using the local Ollama judge
($0 cost — same infra/model as evals/harness/judge_client.py,
evals/finetune/homograph_audit.py, evals/finetune/llm_augment.py; this
module defines its OWN `_call_ollama` rather than importing judge_client's
private one, matching this repo's established per-script convention rather
than reaching across a module boundary at an underscore-prefixed name).

Results are cached to data/failure_taxonomy_cache.json keyed by
"{secret}::{word}" so re-runs are free after the first pass.

Four worked examples (GG's own hand classification of real failing
records — see spec-model-excellence.md's item 5 task prompt) are embedded
in the judge prompt as few-shot calibration anchors, AND separately
sanity-checked post-hoc (sanity_check_worked_examples) against the judge's
own verdict on those exact four records.

Run (from generator/):
    uv run python -m evals.finetune.failure_taxonomy
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
CHECKPOINT_PATH = DATA_DIR / "bakeoff_raw" / "gauravgandhi2411__hinglish-relatedness-sbert.json"
CACHE_PATH = DATA_DIR / "failure_taxonomy_cache.json"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:8b"
TIMEOUT_SECONDS = 90

# Ordinal 0-5, must match evals.harness.topheavy._BAND_NAMES / rival.band_for_rank
# (duplicated here, not imported, because both are private/internal names in
# their home modules — this tuple is a display-only convenience).
BAND_NAMES = ("win", "scorching", "hot", "warm", "cold", "freezing")

CATEGORIES: dict[str, str] = {
    "subword_collision": (
        "The model's embedding for the romanized word was pulled toward "
        "orthographically-similar but semantically UNRELATED English tokens "
        "-- a neighbor-confusion bug, not the word's own spelling."
    ),
    "commonsense_world_knowledge": (
        "The relation requires a specific real-world fact not learnable from "
        "general co-occurrence statistics alone (e.g. 'the moon is a satellite')."
    ),
    "polysemy_gloss_ambiguity": (
        "The English gloss word has multiple senses and the model likely embedded the wrong sense."
    ),
    "transliteration_artifact": (
        "Failure plausibly caused by the ROMANIZED WORD'S OWN spelling being "
        "ambiguous, non-canonical, or inconsistently transliterated -- NOT "
        "about confusion with an unrelated neighbor (that's subword_collision)."
    ),
    "genuine_semantic_difficulty": (
        "A legitimate hard case -- the expected relation is real but subtle "
        "or weak, not a systematic model bug."
    ),
    "label_error": (
        "The benchmark's own near/mid/far tier assignment for this pair is "
        "plausibly WRONG (these tiers are AI-authored, not human-verified)."
    ),
}

# secret, word -> GG's hand classification (spec-model-excellence.md item 5
# task prompt) -- used only for the post-hoc sanity check, never fed back
# into the cache as a shortcut.
GG_ANCHOR_LABELS: dict[tuple[str, str], str] = {
    ("bachpan", "innocence"): "genuine_semantic_difficulty",
    ("chaand", "satellite"): "commonsense_world_knowledge",
    ("bagicha", "yard"): "polysemy_gloss_ambiguity",
    # GG flagged this one as intentionally ambiguous/borderline -- a near-miss
    # is at least as defensible as genuine_semantic_difficulty; the sanity
    # check treats it as a soft match, not a hard pass/fail.
    ("khazana", "gold"): "genuine_semantic_difficulty",
}

_RUBRIC_TEXT = "\n".join(f"- {name}: {desc}" for name, desc in CATEGORIES.items())

_WORKED_EXAMPLES = """Worked examples (human-labeled, use as calibration anchors):
1. secret="bachpan" word="innocence" tier=mid (expected band: warm) actual=freezing (rank 3739)
   -> genuine_semantic_difficulty. Rationale: "childhood implies innocence" is a real but
   abstract/weak association, not a systematic bug.
2. secret="chaand" word="satellite" tier=near (expected bands: win/scorching) actual=freezing
   (rank 3831) -> commonsense_world_knowledge. Rationale: requires knowing "the moon is a
   satellite," a specific fact, not general co-occurrence.
3. secret="bagicha" word="yard" tier=near (expected bands: win/scorching) actual=cold (rank 1256)
   -> polysemy_gloss_ambiguity. Rationale: "yard" has multiple senses (unit of length vs. garden
   yard) and the model likely weighted the wrong one.
4. secret="khazana" word="gold" tier=near (expected bands: win/scorching) actual=hot (rank 518)
   -> genuine_semantic_difficulty (borderline near-miss, intentionally ambiguous calibration
   case -- treasure often means gold specifically, this is close to the expected band already).
"""

_PROMPT_TEMPLATE = """You are auditing failures of a semantic word-relatedness model for a \
Hindi-English (Hinglish) word-guessing game. The model ranks a 10,495-word vocabulary by \
relatedness to a secret word, then bins the rank into a "temperature band" (win=closest ... \
freezing=most distant). A human intended a relation between the secret and a target word to \
fall into a certain expected band(s); the model placed it somewhere else. Classify WHY, using \
EXACTLY one of these six categories:

{rubric}

{worked_examples}

Now classify this failing pair:
secret="{secret}" word="{word}" tier={tier} (subtype={subtype})
Human-intended expected band(s): {expected_band_names}
Model's actual placement: {actual_band_name} (rank {actual_rank} of 10,495){note_line}

Respond with ONLY a JSON object, no other text, no markdown fences:
{{"category": "<one of: {category_keys}>", "rationale": "<one sentence>", \
"confidence": <1-5 int, how confident you are in this classification>}}"""

_CATEGORY_KEYS = ", ".join(CATEGORIES)


class JudgeUnavailableError(RuntimeError):
    """Raised when the local Ollama judge model can't be reached."""


def _call_ollama(prompt: str) -> dict:
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            outer = json.loads(response.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise JudgeUnavailableError(
            f"Could not reach local Ollama judge at {OLLAMA_URL} (model={MODEL}). "
            f"Run `ollama serve` and `ollama pull {MODEL}` first. Underlying error: {e}"
        ) from e
    raw = outer.get("response", "")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise JudgeUnavailableError(f"Judge returned non-JSON output: {raw!r}") from e


def load_failing_records() -> list[dict]:
    """The 124-record failing universe: dim1_records from the shipped
    checkpoint with in_expected_band == False."""
    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return [r for r in checkpoint["dim1_records"] if not r["in_expected_band"]]


def build_prompt(record: dict) -> str:
    """Pure string-formatting -- unit-testable without a live judge."""
    expected_names = "/".join(BAND_NAMES[b] for b in record["expected_bands"])
    actual_name = BAND_NAMES[record["actual_band"]]
    note_line = f"\nNote: {record['note']}" if record.get("note") else ""
    return _PROMPT_TEMPLATE.format(
        rubric=_RUBRIC_TEXT,
        worked_examples=_WORKED_EXAMPLES,
        secret=record["secret"],
        word=record["word"],
        tier=record["tier"],
        subtype=record.get("subtype"),
        expected_band_names=expected_names,
        actual_band_name=actual_name,
        actual_rank=record["actual_rank"],
        note_line=note_line,
        category_keys=_CATEGORY_KEYS,
    )


def _cache_key(secret: str, word: str) -> str:
    return f"{secret}::{word}"


def load_cache() -> dict[str, dict]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def classify_record(record: dict) -> dict:
    """One judge call -> {category, rationale, confidence}, validated
    against the known category set (falls back to a flagged 'unparseable'
    pseudo-category rather than crashing on a malformed response).

    A record with `resolution_error` set (actual_rank/actual_band is None
    because the secret or word isn't in the game's own vocab at all — 3 of
    the 124, e.g. word="migrant") is NOT a semantic-classification question
    the judge can meaningfully answer (there is no "actual placement" to
    explain) — it's short-circuited to the mechanical
    "vocab_resolution_gap" pseudo-category, a structurally different
    failure class (vocab coverage, not model judgment) reported separately
    from the 6-category taxonomy rather than forced into one of those
    buckets.
    """
    if record.get("actual_rank") is None:
        return {
            "category": "vocab_resolution_gap",
            "rationale": record.get("resolution_error") or "word/secret not in vocab",
            "confidence": 5,
        }
    prompt = build_prompt(record)
    parsed = _call_ollama(prompt)
    category = parsed.get("category")
    if category not in CATEGORIES:
        return {
            "category": "unparseable",
            "rationale": f"judge returned unrecognized category={category!r}",
            "confidence": 1,
        }
    return {
        "category": category,
        "rationale": str(parsed.get("rationale", "")),
        "confidence": int(parsed.get("confidence", 3)),
    }


def classify_all_failing(
    records: list[dict] | None = None, cache: dict[str, dict] | None = None
) -> list[dict]:
    """Classify every failing record, cache-first. Saves the cache after
    EVERY new judge call (not just at the end) so a mid-run interruption
    never loses more than one in-flight call's progress -- same
    crash-resilience discipline as benchmark_bakeoff.py's per-model
    checkpointing.
    """
    records = records if records is not None else load_failing_records()
    cache = cache if cache is not None else load_cache()

    results: list[dict] = []
    for r in records:
        key = _cache_key(r["secret"], r["word"])
        if key not in cache:
            cache[key] = classify_record(r)
            save_cache(cache)
        classification = cache[key]
        results.append(
            {
                "secret": r["secret"],
                "word": r["word"],
                "tier": r["tier"],
                "subtype": r.get("subtype"),
                "expected_bands": r["expected_bands"],
                "actual_band": r["actual_band"],
                "actual_rank": r["actual_rank"],
                **classification,
            }
        )
    return results


def sanity_check_worked_examples(classified: list[dict]) -> list[dict]:
    """Compare the judge's own classification of the 4 hand-labeled anchor
    records against GG's calls -- calibration check, not a hard gate (see
    module docstring on the khazana/gold soft-match)."""
    by_key = {(r["secret"], r["word"]): r for r in classified}
    out = []
    for (secret, word), gg_label in GG_ANCHOR_LABELS.items():
        r = by_key.get((secret, word))
        if r is None:
            out.append({"secret": secret, "word": word, "error": "not found in classified results"})
            continue
        out.append(
            {
                "secret": secret,
                "word": word,
                "gg_label": gg_label,
                "judge_label": r["category"],
                "judge_rationale": r["rationale"],
                "agree": r["category"] == gg_label,
            }
        )
    return out


def prevalence_table(classified: list[dict]) -> dict[str, dict]:
    """Category -> {n, pct} over the classified set."""
    n_total = len(classified)
    counts: dict[str, int] = {}
    for r in classified:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    return {
        cat: {"n": n, "pct": (n / n_total) if n_total else None}
        for cat, n in sorted(counts.items(), key=lambda kv: -kv[1])
    }


def low_confidence_flags(classified: list[dict], threshold: int = 2) -> list[dict]:
    """Records the judge itself rated confidence <= threshold -- flagged
    for later human review per spec item 5."""
    return [r for r in classified if r["confidence"] <= threshold]


# Hedge phrases that surface an inconsistent/hand-wavy rationale even when
# the judge's own self-reported confidence score is high — e.g. "chattan"
# (rock) vs. the far-tier decoy "breasts" got confidence=4 but a rationale
# built entirely on "may have"/"may be" hedging, which doesn't actually
# explain HOW the claimed mechanism produced this specific, odd near-miss.
# A pure keyword heuristic, not a judge call — flags for human review, does
# not overrule the judge's category choice.
_HEDGE_PHRASES = ("may have", "may be", "possibly", "might have", "could be", "perhaps")


def inconsistent_rationale_flags(classified: list[dict]) -> list[dict]:
    """Records whose rationale leans on hedging language despite a
    non-low confidence score -- flagged separately from low_confidence_flags
    (spec item 5: 'notably low confidence OR an inconsistent rationale')."""
    out = []
    for r in classified:
        rationale = r.get("rationale", "").lower()
        if any(phrase in rationale for phrase in _HEDGE_PHRASES):
            out.append(r)
    return out


COLLISION_SCAN_REPORT_PATH = DATA_DIR / "collision_scan_report.json"


def load_collision_flagged_secrets(path: Path | None = None) -> set[str] | None:
    """{words flagged as collision-prone} from the sibling collision-scan
    task's output (evals/finetune/collision_scan.py -- WORKSTREAM B item 8,
    scanned/gated independently, not touched by this module). Returns None
    if the report doesn't exist yet (a valid state -- see this module's
    docstring: cross-referencing is a recommended follow-up when absent,
    not a hard dependency)."""
    p = path or COLLISION_SCAN_REPORT_PATH
    if not p.exists():
        return None
    report = json.loads(p.read_text(encoding="utf-8"))
    threshold = report["threshold"]
    return {item["word"] for item in report["full_scan"] if item["collision_score"] >= threshold}


def collision_scan_crossref(classified: list[dict], flagged_secrets: set[str]) -> dict:
    """Cross-reference this taxonomy's per-pair classifications against the
    independent collision scan's flagged-SECRET list (pure aggregation,
    unit-testable given a flagged_secrets set).

    IMPORTANT ASYMMETRY, stated honestly rather than glossed over: this
    taxonomy's subword_collision category asks the judge to reason about
    the failing WORD's own neighbor confusion in isolation -- it never
    shows the judge the SECRET's actual embedding neighbor list. The
    collision scan instead flags a word (often the SECRET here) whose OWN
    neighbor list is dominated by orthographically-similar, semantically-
    unrelated tokens. A secret that is itself collision-prone can push
    legitimate near/mid words out of their expected top ranks WITHOUT the
    failing word itself looking anything like an English homograph -- a
    root cause this taxonomy's per-pair prompt design cannot see. This
    function surfaces how much of the classified prevalence sits on
    collision-flagged secrets, as a signal that true subword_collision
    prevalence may be understated by the raw per-category counts above.
    """
    flagged_records = [r for r in classified if r["secret"] in flagged_secrets]
    unflagged_records = [r for r in classified if r["secret"] not in flagged_secrets]
    return {
        "n_failing_records_with_collision_flagged_secret": len(flagged_records),
        "n_failing_records_total": len(classified),
        "pct_failing_records_with_collision_flagged_secret": (
            len(flagged_records) / len(classified) if classified else None
        ),
        "category_breakdown_flagged_secrets": prevalence_table(flagged_records),
        "category_breakdown_unflagged_secrets": prevalence_table(unflagged_records),
    }


# ---------------------------------------------------------------------------
# Tier/band-width confound check -- discovered while writing up item 5's
# prevalence table: 84/85 (98.8%) of ALL mid-tier records fail, dwarfing
# every other cut in this report. Before attributing that to the model, it
# has to be checked against the BENCHMARK's own design: mid-tier's ONLY
# expected_bands value is [3] (warm), a single band. If that band's rank
# window is implausibly narrow, near-total mid-tier failure is a predictable
# consequence of the benchmark's band width, not (necessarily) a semantic
# failure the judge should be asked to explain pair-by-pair.
# ---------------------------------------------------------------------------


def band_rank_range(band: int, vocab_size: int) -> tuple[int, int]:
    """Inclusive [min_rank, max_rank] for a given band ordinal, derived by
    SCANNING rival.band_for_rank (the canonical, single source of truth for
    band thresholds) rather than duplicating its formula here -- avoids
    silent drift if the thresholds ever change. O(vocab_size), fine for a
    one-off report computation, not a hot path."""
    from rival import band_for_rank  # local import -- avoids a hard dependency at module load

    lo: int | None = None
    hi: int | None = None
    for r in range(1, vocab_size + 1):
        if band_for_rank(r, vocab_size) == band:
            if lo is None:
                lo = r
            hi = r
        elif lo is not None:
            break
    if lo is None or hi is None:
        raise ValueError(f"band {band} never reached for vocab_size={vocab_size}")
    return lo, hi


def tier_band_width_report(all_records: list[dict], vocab_size: int) -> dict:
    """Per-tier: n, in_expected_band rate, and the TOTAL WIDTH (number of
    distinct ranks) of the union of that tier's expected_bands -- surfaces
    whether a tier's poor rate is a benchmark DESIGN artifact (an
    implausibly narrow target window) rather than a pure model-quality
    signal. `all_records` should be the FULL record set (not just failing
    records) so the denominator per tier is correct."""
    by_tier: dict[str, list[dict]] = {}
    for r in all_records:
        by_tier.setdefault(r["tier"], []).append(r)

    out: dict[str, dict] = {}
    for tier, recs in by_tier.items():
        resolved = [r for r in recs if r["actual_rank"] is not None]
        expected_bands_set: set[int] = set()
        for r in recs:
            expected_bands_set.update(r["expected_bands"])
        total_width = sum(
            band_rank_range(b, vocab_size)[1] - band_rank_range(b, vocab_size)[0] + 1
            for b in expected_bands_set
        )
        n_resolved = len(resolved)
        n_pass = sum(1 for r in resolved if r["in_expected_band"])
        rate = (n_pass / n_resolved) if n_resolved else None
        out[tier] = {
            "n": len(recs),
            "n_resolved": n_resolved,
            "n_pass": n_pass,
            "n_fail": n_resolved - n_pass,
            "in_expected_band_rate": rate,
            "expected_bands": sorted(expected_bands_set),
            "target_window_ranks": total_width,
            "target_window_pct_of_vocab": total_width / vocab_size,
        }
    return out


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    failing = load_failing_records()
    print(f"n_failing: {len(failing)}")
    classified = classify_all_failing(failing)
    prevalence = prevalence_table(classified)
    print("prevalence:")
    for cat, stats in prevalence.items():
        print(f"  {cat}: n={stats['n']} ({stats['pct']:.1%})")
    sanity = sanity_check_worked_examples(classified)
    print("worked-example sanity check:")
    for s in sanity:
        print(
            f"  {s['secret']} <- {s['word']}: gg={s.get('gg_label')} "
            f"judge={s.get('judge_label')} agree={s.get('agree')}"
        )
    low_conf = low_confidence_flags(classified)
    print(f"low-confidence flags (<=2): {len(low_conf)}")
    hedged = inconsistent_rationale_flags(classified)
    print(f"hedge-language flags: {len(hedged)}")
    for h in hedged:
        print(
            f"  {h['secret']} <- {h['word']} [{h['category']}, conf={h['confidence']}]: "
            f"{h['rationale']}"
        )
