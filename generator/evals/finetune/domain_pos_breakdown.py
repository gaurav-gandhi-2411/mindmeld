from __future__ import annotations

"""
Per-domain and per-POS/concreteness breakdown of the shipped model's dim1
failures (spec-model-excellence.md WORKSTREAM B item 7).

Domain: domain labels exist ONLY for the 34 benchmark-supplement secrets
(evals.gen_dim1_benchmark_supplement.BENCHMARK_SUPPLEMENT_PAIRS, a
`list[tuple[hien_secret, en_gloss, domain]]` — not threaded into the
scenario JSON, joined here by `secret`). The original 25 production
secrets (evals/scenarios/dim1_hien.json) carry NO domain label and none is
invented for them here — their records are reported separately as
"unlabeled / out of scope for this cut", never guessed.

POS + concreteness: fully greenfield — this repo has no spaCy/nltk
dependency (confirmed) and none is added here. The word set is code-mixed
(English glosses + romanized Hindi terms), so the local Ollama judge (same
$0 infra as failure_taxonomy.py / judge_client.py) classifies POS
(noun/verb/adjective/other) and concreteness (concrete/abstract) per
UNIQUE `word` across the 379 dim1_records, cached to
data/pos_concreteness_cache.json.

BOTH the domain join for the 34 new secrets AND the POS/concreteness tags
are AI-derived labels, not human-verified ground truth — same epistemic
status as this benchmark's own near/mid/far tiers (spec-model-excellence.md
Workstream D item 13 flags this as an open question for the benchmark
generally). Treat this module's output as a first-pass systematic view,
not a final verdict.

Run (from generator/):
    uv run python -m evals.finetune.domain_pos_breakdown
"""

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from evals.gen_dim1_benchmark_supplement import BENCHMARK_SUPPLEMENT_PAIRS

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
POS_CACHE_PATH = DATA_DIR / "pos_concreteness_cache.json"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:8b"
# 240s, not 90s -- observed cold-load timeouts mid-run (Ollama unloads the
# model after an idle period; a cold reload alone took up to ~75s in
# practice under CONTENTION from another concurrently-running Ollama-backed
# script in this same session -- see this module's own module docstring on
# why sequential-only Ollama access was already this repo's documented
# finding for CPU-bound inference; 240s gives real headroom rather than
# chasing another spurious-timeout retry loop), same rationale as
# build_devanagari_front_end.py raising llm_augment's default timeout.
TIMEOUT_SECONDS = 240

POS_VALUES = ("noun", "verb", "adjective", "other")
CONCRETENESS_VALUES = ("concrete", "abstract")

_POS_PROMPT = """Classify the word "{word}" as it would most commonly be used in a Hindi-English \
(Hinglish) word-guessing game -- the word may be an English gloss or a romanized Hindi term.

1. part_of_speech: its most common part of speech -- one of: noun, verb, adjective, other.
2. concreteness: is the concept CONCRETE (a physical, perceivable thing -- e.g. "rock", "chaabi"/\
key) or ABSTRACT (an idea, emotion, or relation with no physical form -- e.g. "freedom", "chinta"/\
worry)? One of: concrete, abstract.

Respond with ONLY a JSON object, no other text, no markdown fences:
{{"part_of_speech": "<noun|verb|adjective|other>", "concreteness": "<concrete|abstract>"}}"""


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


# ---------------------------------------------------------------------------
# Domain join -- pure function, unit-testable.
# ---------------------------------------------------------------------------


def secret_domain_map() -> dict[str, str]:
    """{hien_secret: domain} for the 34 benchmark-supplement secrets only."""
    return {hien: domain for hien, _en_gloss, domain in BENCHMARK_SUPPLEMENT_PAIRS}


def join_domain(dim1_records: list[dict], domain_map: dict[str, str]) -> list[dict]:
    """Attach `domain` to each record (None + explicit `domain_labeled=False`
    for the 25 original production secrets, which carry no domain label)."""
    out = []
    for r in dim1_records:
        joined = dict(r)
        domain = domain_map.get(r["secret"])
        joined["domain"] = domain
        joined["domain_labeled"] = domain is not None
        out.append(joined)
    return out


def domain_report(joined_records: list[dict]) -> dict:
    """Per-domain in_expected_band rate + n, for the domain-labeled subset
    only; the unlabeled (original 25 secrets) subset is reported
    separately with an explicit coverage caveat (spec item 7)."""
    resolved = [r for r in joined_records if r["actual_rank"] is not None]
    labeled = [r for r in resolved if r["domain_labeled"]]
    unlabeled = [r for r in resolved if not r["domain_labeled"]]

    domains = sorted({r["domain"] for r in labeled})
    by_domain: dict[str, dict] = {}
    for d in domains:
        subset = [r for r in labeled if r["domain"] == d]
        n = len(subset)
        rate = sum(1 for r in subset if r["in_expected_band"]) / n if n else None
        by_domain[d] = {"n": n, "in_expected_band_rate": rate}

    unlabeled_rate = (
        sum(1 for r in unlabeled if r["in_expected_band"]) / len(unlabeled) if unlabeled else None
    )

    return {
        "by_domain": by_domain,
        "n_domain_labeled_records": len(labeled),
        "unlabeled": {
            "n": len(unlabeled),
            "in_expected_band_rate": unlabeled_rate,
            "caveat": (
                "these 25-secret production records carry no domain label -- "
                "reported here for completeness, out of scope for the per-domain cut"
            ),
        },
    }


# ---------------------------------------------------------------------------
# POS/concreteness classification (judge-backed).
# ---------------------------------------------------------------------------


def unique_words(dim1_records: list[dict]) -> list[str]:
    """Sorted unique `word` values across all records -- pure, testable."""
    return sorted({r["word"] for r in dim1_records})


def load_pos_cache() -> dict[str, dict]:
    if POS_CACHE_PATH.exists():
        return json.loads(POS_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_pos_cache(cache: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POS_CACHE_PATH.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def classify_word_pos(word: str) -> dict:
    parsed = _call_ollama(_POS_PROMPT.format(word=word))
    pos = parsed.get("part_of_speech")
    conc = parsed.get("concreteness")
    return {
        "part_of_speech": pos if pos in POS_VALUES else "other",
        "concreteness": conc if conc in CONCRETENESS_VALUES else "abstract",
    }


def classify_all_words(
    words: list[str] | None = None, cache: dict[str, dict] | None = None
) -> dict[str, dict]:
    """word -> {part_of_speech, concreteness}, cache-first. Saves after
    every new call (same crash-resilience discipline as
    failure_taxonomy.classify_all_failing). A transient JudgeUnavailableError
    on a SINGLE word (observed in practice: Ollama unloads the model after
    an idle period, and a cold reload can occasionally exceed even a
    generous timeout) is logged and skipped rather than aborting the whole
    batch -- the word simply stays uncached and gets picked up on the next
    run, same resumability contract as the rest of this batch."""
    words = words if words is not None else []
    cache = cache if cache is not None else load_pos_cache()
    for w in words:
        if w not in cache:
            try:
                cache[w] = classify_word_pos(w)
            except JudgeUnavailableError as e:
                logger.warning("skipping word=%r after judge error: %s", w, e)
                continue
            save_pos_cache(cache)
    return cache


def join_pos_concreteness(dim1_records: list[dict], pos_map: dict[str, dict]) -> list[dict]:
    out = []
    for r in dim1_records:
        joined = dict(r)
        info = pos_map.get(r["word"])
        joined["part_of_speech"] = info["part_of_speech"] if info else None
        joined["concreteness"] = info["concreteness"] if info else None
        out.append(joined)
    return out


def pos_report(joined_records: list[dict]) -> dict:
    resolved = [r for r in joined_records if r["actual_rank"] is not None and r["part_of_speech"]]
    pos_values = sorted({r["part_of_speech"] for r in resolved})
    by_pos: dict[str, dict] = {}
    for p in pos_values:
        subset = [r for r in resolved if r["part_of_speech"] == p]
        n = len(subset)
        rate = sum(1 for r in subset if r["in_expected_band"]) / n if n else None
        by_pos[p] = {"n": n, "in_expected_band_rate": rate}
    return by_pos


def concreteness_report(joined_records: list[dict]) -> dict:
    resolved = [r for r in joined_records if r["actual_rank"] is not None and r["concreteness"]]
    conc_values = sorted({r["concreteness"] for r in resolved})
    by_conc: dict[str, dict] = {}
    for c in conc_values:
        subset = [r for r in resolved if r["concreteness"] == c]
        n = len(subset)
        rate = sum(1 for r in subset if r["in_expected_band"]) / n if n else None
        by_conc[c] = {"n": n, "in_expected_band_rate": rate}
    return by_conc


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    checkpoint = json.loads(
        (DATA_DIR / "bakeoff_raw" / "gauravgandhi2411__hinglish-relatedness-sbert.json").read_text(
            encoding="utf-8"
        )
    )
    records = checkpoint["dim1_records"]

    domain_map = secret_domain_map()
    joined_domain = join_domain(records, domain_map)
    print(json.dumps(domain_report(joined_domain), indent=2))

    words = unique_words(records)
    print(f"n_unique_words: {len(words)}")
    pos_map = classify_all_words(words)
    joined_pos = join_pos_concreteness(records, pos_map)
    print(json.dumps(pos_report(joined_pos), indent=2))
    print(json.dumps(concreteness_report(joined_pos), indent=2))
