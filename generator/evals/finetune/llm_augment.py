from __future__ import annotations

"""
LLM-augmented Hinglish (word, related, unrelated) triplet generation — $0,
local Ollama qwen3:8b, no API key (same model/harness pattern as
evals/harness/judge_client.py).

Two isolated stages, same rationale as judge_client.py's split spoiler/
solvability calls: a single compound "generate AND self-judge" prompt lets
the model rubber-stamp its own bad generations, so generation and quality
filtering are separate calls here too.

Stage 1 — generation: one call per domain, asking for a JSON array of
{"word", "related", "unrelated"} triplets in that domain. `word` is a
romanized Hindi/Hinglish term; `related` is a genuine synonym/strong
associate (Hindi or English); `unrelated` is a plausible-looking but
semantically unconnected word. The prompt explicitly excludes the frozen
held-out secret list (see split.py) so no generated triplet can anchor on
a word this fine-tune is supposed to be evaluated on.

Stage 2 — quality filter: two isolated per-triplet judge calls (mirrors
judge_client.py's isolation finding — bundled checks are less reliable):
  - "related_ok": is `related` actually a good synonym/associate of `word`?
  - "unrelated_ok": is `unrelated` actually unconnected to `word`?
A triplet ships only if both pass. Family-friendly + held-out-secret
filtering is re-checked post-generation (never trust the model followed
the instruction) via profanity.py blocklists and a membership check against
the held-out set.
"""

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:8b"
TIMEOUT_SECONDS = 90

DOMAINS = [
    "family and relationships",
    "food and cooking",
    "festivals and celebrations",
    "nature and weather",
    "emotions and feelings",
    "daily routine and time",
    "work and money",
    "school and education",
    "sports and games",
    "bollywood and music",
    "home and household objects",
    "travel and places",
    "body and health",
    "animals",
    "clothing and fashion",
    "religion and spirituality",
    "technology and gadgets",
    "transport and vehicles",
    "colors and numbers",
    "cricket",
]

N_PER_DOMAIN = 35

_GENERATE_PROMPT = """You are building training data for a Hindi-English (Hinglish) word \
association game. Generate {n} DIVERSE (word, related, unrelated) triplets for the domain: \
"{domain}".

Rules for each triplet:
- "word": a common, family-friendly romanized Hindi or Hinglish word (lowercase, no diacritics).
- "related": a genuine synonym or strong semantic associate of "word" — can be English or \
Hinglish, something a fluent Hindi-English speaker would immediately recognize as connected.
- "unrelated": a common word that is semantically UNCONNECTED to "word" (not a synonym, not an \
associate, not in the same domain) — but still a real, ordinary word (not gibberish).
- Every field must be a SINGLE word, not a phrase (no spaces).
- Do not use any of these words in any field (they are reserved for evaluation): {excluded}
- Keep everything family-friendly.

Respond with ONLY a JSON array, no other text, no markdown fences:
[{{"word": "...", "related": "...", "unrelated": "..."}}, ...]"""

_RELATED_CHECK_PROMPT = """In a Hindi-English (Hinglish) word association game, is "{related}" \
a genuine synonym or strong semantic associate of "{word}"? Answer strictly — if the connection \
is weak, forced, or only tangential, say false.

Respond with ONLY: {{"related_ok": <true|false>}}"""

_UNRELATED_CHECK_PROMPT = """In a Hindi-English (Hinglish) word association game, is "{unrelated}" \
semantically UNCONNECTED to "{word}" (not a synonym, not an associate, not in the same domain, \
not commonly used together)? Answer strictly — if there is any real connection, say false.

Respond with ONLY: {{"unrelated_ok": <true|false>}}"""


class LLMUnavailableError(RuntimeError):
    pass


_TRIPLET_ARRAY_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "word": {"type": "string"},
            "related": {"type": "string"},
            "unrelated": {"type": "string"},
        },
        "required": ["word", "related", "unrelated"],
    },
}


def _call_ollama(prompt: str, response_format: str | dict = "json") -> dict | list:
    # Plain "json" format mode collapses multi-item generations to a single
    # object on this model (observed empirically — asking for N triplets with
    # format="json" returns ONE triplet, not an array). Passing an explicit
    # JSON-schema `format` (Ollama structured outputs) fixes this reliably —
    # used for the array-producing generation calls; the true/false judge
    # calls keep plain "json" since they're single small objects.
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": response_format,
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            outer = json.loads(response.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise LLMUnavailableError(
            f"Could not reach local Ollama at {OLLAMA_URL} (model={MODEL}). "
            f"Run `ollama serve` and `ollama pull {MODEL}` first. Underlying error: {e}"
        ) from e
    raw = outer.get("response", "")
    return json.loads(raw)


def generate_domain_triplets(domain: str, n: int, excluded: set[str]) -> list[dict]:
    """One generation call for `domain`. Returns raw (unfiltered) triplets;
    may be shorter than `n` or contain junk — caller filters."""
    prompt = _GENERATE_PROMPT.format(
        n=n, domain=domain, excluded=", ".join(sorted(excluded)) or "(none)"
    )
    try:
        raw = _call_ollama(prompt, response_format=_TRIPLET_ARRAY_SCHEMA)
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("generation failed for domain=%r: %s", domain, e)
        return []
    if isinstance(raw, dict):
        # Some models wrap the array in {"triplets": [...]}
        for key in ("triplets", "items", "results"):
            if key in raw and isinstance(raw[key], list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        logger.warning("unexpected generation shape for domain=%r: %r", domain, type(raw))
        return []
    out = []
    for rec in raw:
        if (
            isinstance(rec, dict)
            and isinstance(rec.get("word"), str)
            and isinstance(rec.get("related"), str)
            and isinstance(rec.get("unrelated"), str)
        ):
            out.append(
                {
                    "word": rec["word"].strip().lower(),
                    "related": rec["related"].strip().lower(),
                    "unrelated": rec["unrelated"].strip().lower(),
                    "domain": domain,
                }
            )
    return out


def quality_filter(triplet: dict) -> bool:
    """Two isolated judge calls; both must pass."""
    try:
        related_resp = _call_ollama(
            _RELATED_CHECK_PROMPT.format(word=triplet["word"], related=triplet["related"])
        )
        unrelated_resp = _call_ollama(
            _UNRELATED_CHECK_PROMPT.format(word=triplet["word"], unrelated=triplet["unrelated"])
        )
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("judge call failed for %r: %s", triplet, e)
        return False
    return bool(related_resp.get("related_ok")) and bool(unrelated_resp.get("unrelated_ok"))


def generate_and_filter(
    excluded: set[str],
    profanity_blocklists: tuple[frozenset[str], frozenset[str]],
    domains: list[str] | None = None,
    n_per_domain: int = N_PER_DOMAIN,
) -> tuple[list[dict], dict]:
    """
    Full pipeline: generate raw triplets per domain, drop anything touching
    `excluded` (case-insensitive) or profanity, then quality-filter the rest.

    Returns (accepted_triplets, stats).
    """
    en_profanity, hi_profanity = profanity_blocklists
    excluded_lower = {w.lower() for w in excluded}

    raw_all: list[dict] = []
    for domain in domains or DOMAINS:
        raw_all.extend(generate_domain_triplets(domain, n_per_domain, excluded_lower))

    n_generated = len(raw_all)

    def _clean(rec: dict) -> bool:
        for field in ("word", "related", "unrelated"):
            w = rec[field]
            if not w or not w.isalpha():
                return False
            if w in excluded_lower:
                return False
            if w in en_profanity or w in hi_profanity:
                return False
        if rec["word"] == rec["related"] or rec["word"] == rec["unrelated"]:
            return False
        return rec["related"] != rec["unrelated"]

    candidates = [r for r in raw_all if _clean(r)]
    n_after_clean = len(candidates)

    # Dedup exact (word, related, unrelated) triples.
    seen = set()
    deduped = []
    for r in candidates:
        key = (r["word"], r["related"], r["unrelated"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    candidates = deduped
    n_after_dedup = len(candidates)

    accepted = [r for r in candidates if quality_filter(r)]

    stats = {
        "n_generated_raw": n_generated,
        "n_after_clean_filter": n_after_clean,
        "n_after_dedup": n_after_dedup,
        "n_accepted_after_judge": len(accepted),
    }
    return accepted, stats
