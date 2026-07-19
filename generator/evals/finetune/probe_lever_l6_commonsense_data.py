from __future__ import annotations

"""
Cheap probe for lever L6 (spec-residual-attack.md) -- "commonsense-shaped
training data ... distinct from the failed co-occurrence hard-negatives".

Background: docs/known-limitations.md entry 20 documents an associative-
commonsense residual -- world-knowledge facts (a food's taste/color/texture,
a place's characteristic sound) that a pure co-occurrence embedding
structurally under-ranks, because the fact is rarely stated as plain
co-occurring text (you learn "watermelon is red" from cutting one open, not
from reading about watermelons). A prior probe pass hand-curated + no-leakage
-verified 8 game-vocab (secret, related-property-word) edges with
justifications -- evals/finetune/data/commonsense_residual_candidates.json --
which this probe treats as a FROZEN, NEVER-TRAINED-ON held-out eval set.

Distinct from a parallel lever (L4, knowledge distillation targeted directly
at these 8 words -- an inherently overfit-prone "can we fix these specific
words" test): L6 is the opposite, more rigorous test. It builds a BROADER set
of commonsense-shaped training pairs (word, property, value) across MANY
OTHER game-vocab words -- same domains, same taste/color/texture/sound/
function pattern as the 8 curated examples -- trains a LoRA probe on THOSE,
and measures whether the model GENERALIZES the property-association SKILL to
the 8 held-out curated words it never saw in training. This is the
scientifically meaningful generalization test spec-residual-attack.md's own
risk section calls for ("attacking specific residual words risks tuning to
the benchmark").

Teacher model DEVIATION (documented, not silent): the task brief specifies
the local Ollama teacher qwen3:8b (llm_augment.py's MODEL constant). At probe
time, `ollama list` against the running server initially showed only
llama3.1:8b and gemma2:9b (qwen3:8b missing); a live `ollama pull qwen3:8b`
stalled at 0%/5.2GB with no throughput for several minutes. The stalled
server process was killed and Ollama auto-restarted with its full, correct
model catalog (qwen3:8b WAS actually already present, 7 weeks old -- the
first server process queried was evidently stale/misconfigured), but by then
a direct qwen3:8b generate call still timed out at 180s under severe GPU
contention (`nvidia-smi` showed the single RTX 3070 at 100% util / 7.9-8.0GB
of 8GB VRAM already held by a concurrent process -- almost certainly a
sibling lever's GCP/local training run from this same research wave), while
an equivalent llama3.1:8b call on the same server returned in 5.6s. This
exact substitution was already precedented in this same research wave by
probe_lever_l2_devanagari_hybrid.py's `_llm_devanagari_batch_llama` (same
finding: qwen3:8b unavailable/too slow, llama3.1:8b substituted, same wire
protocol). This probe follows the identical pattern: TEACHER_MODEL =
"llama3.1:8b", tagged explicitly in every accepted candidate's provenance,
never silently assumed to be qwen3:8b.

Four-step pipeline:
  1. Mine/generate a property-grounded (word, gloss, property, value) fact
     per candidate via a NEW prompt template (materially different from
     llm_augment.generate_domain_triplets's generic "related/unrelated"
     triplet prompt -- this one explicitly asks for taste/color/texture/
     sound/function property associations), across food/nature/animal/
     material domains -- the domains the 8 curated examples come from.
     Quality-filtered with the SAME isolated-judge pattern
     llm_augment.quality_filter() uses (two SEPARATE judge calls per
     candidate, not one compound self-judged call -- this repo's own
     calibration finding: isolation raised agreement 59%->97%, see
     judge_client.py's docstring precedent).
  2. Mine a hard negative per accepted candidate using hard_negatives.py's
     exact rank-band-50-500 approach (imported constants, reimplemented
     in-memory against the OFF-THE-SHELF model -- explicit `_model_override`,
     not relying on config.py's mutable default, which currently points at
     the SHIPPED model -- see module-level note below), building MNRL
     triplets + graded pairs matching train_graded_pairs.jsonl's exact
     schema.
  3. Trains a LoRA probe with the proven obj_hard_neg recipe (r=8/alpha=16/
     lr=2e-4/4 epochs/early_stopping_patience=2/seed=42), extending the
     EXISTING shipped training set (train_mnrl_pairs_hard_neg.jsonl +
     train_graded_pairs.jsonl) in-memory with the new commonsense pairs --
     never touching disk, same pattern as probe_subword_collision.py's
     `build_extended_training_set`.
  4. Evaluates on TWO independent rulers:
     a. Generalization (the key L6 question): for all 8 HELD-OUT curated
        words (never in this probe's training set -- verified
        programmatically, not by intent), recompute the `related` property
        word's rank under the new checkpoint vs the shipped model, using
        probe_lever_l5_rank_override.compute_ranks (the exact same rank
        algorithm as payload._build_payload_core, reused not reimplemented).
     b. Full-benchmark regression floor: the frozen public 34-secret
        benchmark, paired-bootstrap vs the shipped model's cached bakeoff
        checkpoint -- reusing probe_subword_collision.py's exact
        comparator/scoring functions (same functions probe_lever_l1_capacity
        .py reuses), for apples-to-apples comparability across this wave's
        lever-probe table.

Hard-negative mining model note: `hard_negatives.py`'s own module docstring
describes mining against "the OFF-THE-SHELF (pre-fine-tune) model" -- true
when it was originally run (before config.py's "hi-en" default was updated
to point at the shipped fine-tune post-ship). Calling `embed_vocab(vocab,
"hi-en")` with no override TODAY would silently use the SHIPPED model
instead, which would be a different (and inconsistent-with-the-rest-of-the-
training-set) mining basis. This probe is explicit -- always wraps mining in
`with _model_override(OFF_THE_SHELF_MODEL):` -- rather than depending on
config.py's current mutable default, since `run_training` always starts LoRA
fine-tuning from a fresh OFF_THE_SHELF_MODEL load (never continues from the
shipped checkpoint), matching the basis every other pair in
train_mnrl_pairs_hard_neg.jsonl was mined against.

Run (from generator/):
    uv run python -m evals.finetune.probe_lever_l6_commonsense_data --generate
    uv run python -m evals.finetune.probe_lever_l6_commonsense_data --train
    uv run python -m evals.finetune.probe_lever_l6_commonsense_data --eval
"""

import argparse
import json
import logging
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from embeddings import cosine_similarities, embed_vocab
from evals.finetune.bootstrap_ci import (
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import OFF_THE_SHELF_MODEL, _model_override
from evals.finetune.hard_negatives import HARD_NEG_RANK_HI, HARD_NEG_RANK_LO, MIN_LEVENSHTEIN
from evals.finetune.llm_augment import LLMUnavailableError
from evals.finetune.probe_lever_l5_rank_override import compute_ranks
from evals.finetune.probe_subword_collision import (
    _public_benchmark_dim1_records,
    _public_benchmark_dim2_result,
    _shipped_model_dim1_records_34,
    _shipped_model_dim2_records_34,
    build_exclude_set,
)
from evals.finetune.train_lib import DATA_DIR, TrainConfig, run_training
from evals.harness.dimension1_ranking import _band_accuracy
from payload import levenshtein
from profanity import load_en_profanity, load_hi_profanity
from vocab import load_hien_vocab

logger = logging.getLogger(__name__)

RUN_NAME = "probe_lever_l6_commonsense_data"
SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"

HELD_OUT_CANDIDATES_PATH = DATA_DIR / "commonsense_residual_candidates.json"
PAIRS_OUT_PATH = DATA_DIR / "probe_lever_l6_commonsense_pairs.jsonl"
RESULT_PATH = DATA_DIR / f"{RUN_NAME}.eval_result.json"

# --- teacher (see module docstring's DEVIATION note) --------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
TEACHER_MODEL = "llama3.1:8b"  # deviation from spec's qwen3:8b -- see docstring
# This machine ran under heavy, INTERMITTENT concurrent GPU contention from
# other processes during this probe (nvidia-smi repeatedly showed the single
# RTX 3070 pinned at 97-100% util / 7.3-7.9 of 8GB VRAM held by PIDs unrelated
# to this probe, fluctuating over multiple hours). A long timeout (240s) +
# few retries meant ONE stuck call could burn an entire background-task
# lifetime with nothing to show for it. SHORT timeout + more, cheap retries
# is the better fit for this bursty-availability environment -- a failed
# attempt costs seconds, not minutes, so more attempts fit in the same wall
# clock and the pipeline makes forward progress whenever the GPU is briefly
# free, per rule 108 (timeout + retry+backoff+jitter + defined failure
# behavior on every outbound call).
TIMEOUT_SECONDS = 30
MAX_RETRIES = 2
RETRY_BACKOFF_BASE_S = 3.0  # exponential backoff + jitter, per rule 108

# Same domains the 8 curated examples come from (food x6, nature x1 --
# tarbooz/anaar/nariyal/samosa/mirch/til/dudh are food, jharna is nature) plus
# animals + household-object/material domains per the task's explicit
# "food/nature/animal/material" framing, so the mined skill generalizes
# across MORE than just the food domain the curated set happens to skew to.
DOMAINS: list[str] = [
    "food and cooking",
    "nature and weather",
    "animals",
    "home and household objects",
]
N_PER_CALL = 10
CALLS_PER_DOMAIN = 2  # 2x lighter calls per domain rather than 1 heavy call --
# splits failure risk under contention (module docstring's DEVIATION note) so
# one dropped call doesn't zero out an entire domain.
PROPERTY_TYPES = frozenset({"taste", "color", "texture", "sound", "function"})

_FACT_ARRAY_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "word": {"type": "string"},
            "gloss": {"type": "string"},
            "property": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["word", "gloss", "property", "value"],
    },
}

# Property-grounded generation prompt -- MATERIALLY DIFFERENT from
# llm_augment._GENERATE_PROMPT's generic (word, related, unrelated) triplet
# ask: this explicitly targets the taste/color/texture/sound/function
# property-association PATTERN the residual is about, not generic semantic
# relatedness (which co-occurrence hard-negative mining already covers and
# proved dead, docs/known-limitations.md entry 20 LEVER 1).
_GENERATE_PROMPT = """You are building training data for a Hindi-English (Hinglish) word-\
association game focused on ASSOCIATIVE / WORLD-KNOWLEDGE properties -- facts you know from \
experiencing an object (seeing, tasting, touching, hearing, using it), NOT from how words are \
typically used together in text.

Generate {n} DIVERSE (word, property, value) facts for the domain: "{domain}".

Rules for each fact:
- "word": a common, family-friendly romanized Hindi or Hinglish word naming a concrete object/ \
place/food/animal (lowercase, single word, no diacritics, no spaces).
- "gloss": the word's English meaning (single word, lowercase).
- "property": exactly one of "taste", "color", "texture", "sound", or "function" -- pick whichever \
property is the SINGLE MOST DEFINING, well-known sensory or functional fact about this word.
- "value": the SPECIFIC value of that property (a single English or Hinglish word, e.g. "red", \
"sour", "rough", "loud", "cutting") -- something a person who has actually seen/tasted/touched/ \
used/heard "word" would immediately agree with, not a generic or vague word.
- Every field must be a SINGLE word, not a phrase (no spaces).
- Do not use any of these words in any field (reserved for evaluation): {excluded}
- Keep everything family-friendly.

Respond with ONLY a JSON array, no other text, no markdown fences:
[{{"word": "...", "gloss": "...", "property": "taste|color|texture|sound|function", \
"value": "..."}}, ...]"""

# Isolated judge 1/2 -- is the claimed property genuinely true and well-known?
_PROPERTY_OK_PROMPT = """In a Hindi-English (Hinglish) word-association game, is it TRUE and \
WELL-KNOWN that "{word}" ({gloss}) has {property} = "{value}"? This should be a fact someone would \
know from actually seeing/tasting/touching/using/hearing "{gloss}", not a guess or forced \
connection. Answer strictly -- if uncertain, only loosely true, or forced, say false.

Respond with ONLY: {{"property_ok": <true|false>}}"""

# Isolated judge 2/2 -- is the value specific/concrete rather than a vague
# catch-all that would trivially "pass" for almost any word (hallucination
# guard against the model padding with generic filler like "good"/"nice").
_SPECIFIC_OK_PROMPT = """Is "{value}" a SPECIFIC, concrete {property} descriptor (like "sour", \
"crimson", "rough", "crunchy", "cutting") rather than a vague or generic word (like "good", \
"nice", "normal", "thing", "special") that could apply to almost anything? Answer strictly.

Respond with ONLY: {{"specific_ok": <true|false>}}"""


def _call_teacher(prompt: str, response_format: str | dict = "json") -> dict | list:
    """Same wire protocol as llm_augment._call_ollama, pointed at
    TEACHER_MODEL instead of the module-level qwen3:8b constant (which
    _call_ollama does not take as a parameter) -- mirrors
    probe_lever_l2_devanagari_hybrid.py's `_llm_devanagari_batch_llama`
    substitution precedent exactly. Retries with exponential backoff + jitter
    (rule 108 -- every outbound call gets a timeout, retry, defined failure
    behavior) since this probe ran under sustained, heavy GPU contention from
    a concurrent sibling process (see module docstring); a single-attempt
    call observed a near-100% failure rate under that load."""
    body = json.dumps(
        {
            "model": TEACHER_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": response_format,
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                outer = json.loads(response.read())
            raw = outer.get("response", "")
            return json.loads(raw)
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                delay = RETRY_BACKOFF_BASE_S * (2**attempt) + random.uniform(0, 2.0)
                logger.warning(
                    "teacher call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    delay,
                    e,
                )
                time.sleep(delay)
    raise LLMUnavailableError(
        f"Could not reach local Ollama at {OLLAMA_URL} (model={TEACHER_MODEL}) after "
        f"{MAX_RETRIES + 1} attempts. Run `ollama serve` and `ollama pull {TEACHER_MODEL}` "
        f"first. Underlying error: {last_error}"
    ) from last_error


def check_ollama_up() -> bool:
    """True iff a local Ollama server answers /api/tags. Never assumed."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


# ---------------------------------------------------------------------------
# Held-out set (the 8 curated words this probe must NEVER train on)
# ---------------------------------------------------------------------------


def load_held_out_candidates() -> list[dict]:
    return json.loads(HELD_OUT_CANDIDATES_PATH.read_text(encoding="utf-8"))


def held_out_anchor_words() -> frozenset[str]:
    return frozenset(c["word"].lower() for c in load_held_out_candidates())


# ---------------------------------------------------------------------------
# Step 1: generate + isolated-judge quality filter
# ---------------------------------------------------------------------------


def generate_domain_facts(domain: str, n: int, excluded: set[str]) -> list[dict]:
    """One generation call for `domain`. Returns raw (unfiltered) facts; may
    be shorter than `n` or contain junk -- caller filters."""
    prompt = _GENERATE_PROMPT.format(
        n=n, domain=domain, excluded=", ".join(sorted(excluded)) or "(none)"
    )
    try:
        raw = _call_teacher(prompt, response_format=_FACT_ARRAY_SCHEMA)
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("generation failed for domain=%r: %s", domain, e)
        return []
    if isinstance(raw, dict):
        for key in ("facts", "items", "results"):
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
            and isinstance(rec.get("gloss"), str)
            and isinstance(rec.get("property"), str)
            and isinstance(rec.get("value"), str)
        ):
            out.append(
                {
                    "word": rec["word"].strip().lower(),
                    "gloss": rec["gloss"].strip().lower(),
                    "property": rec["property"].strip().lower(),
                    "value": rec["value"].strip().lower(),
                    "domain": domain,
                }
            )
    return out


def _clean_candidate(
    c: dict,
    excluded_lower: set[str],
    exclude_set: frozenset[str],
    held_out_anchors: frozenset[str],
    profanity: frozenset[str],
    vocab_set: set[str],
) -> bool:
    """Cheap, non-LLM structural/no-leakage filter, applied BEFORE the
    (expensive) isolated judge calls -- mirrors llm_augment.generate_and_
    filter's `_clean` ordering."""
    if c["property"] not in PROPERTY_TYPES:
        return False
    for field in ("word", "value"):
        w = c[field]
        if not w or not w.isalpha():
            return False
        if w in excluded_lower or w in exclude_set or w in profanity:
            return False
    if c["word"] in held_out_anchors:
        return False
    if c["word"] not in vocab_set:
        # teacher hallucinated a word that isn't real game vocabulary
        return False
    return c["word"] != c["value"]


def property_ok_judge(c: dict) -> bool:
    try:
        resp = _call_teacher(
            _PROPERTY_OK_PROMPT.format(
                word=c["word"], gloss=c["gloss"], property=c["property"], value=c["value"]
            )
        )
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("property_ok judge failed for %r: %s", c, e)
        return False
    return bool(resp.get("property_ok"))


def specific_ok_judge(c: dict) -> bool:
    try:
        resp = _call_teacher(
            _SPECIFIC_OK_PROMPT.format(property=c["property"], value=c["value"])
        )
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("specific_ok judge failed for %r: %s", c, e)
        return False
    return bool(resp.get("specific_ok"))


def quality_filter(c: dict) -> bool:
    """Two ISOLATED judge calls; both must pass -- same isolation pattern as
    llm_augment.quality_filter (separate calls per claim, not one compound
    self-judged call)."""
    return property_ok_judge(c) and specific_ok_judge(c)


def generate_and_filter_domain(
    domain: str,
    excluded_lower: set[str],
    exclude_set: frozenset[str],
    held_out_anchors: frozenset[str],
    profanity: frozenset[str],
    vocab_set: set[str],
    already_seen: set[tuple[str, str]],
) -> tuple[list[dict], dict]:
    """ONE domain's worth of generate -> clean-filter -> dedup (against both
    this batch and `already_seen`, so re-invoking across multiple process
    runs -- see mine_and_save_pairs's incremental-persistence design -- never
    re-accepts a (word, value) pair already on disk) -> isolated-judge
    quality filter. Returns (accepted_candidates, domain_stats)."""
    raw: list[dict] = []
    n_calls = 0
    for _ in range(CALLS_PER_DOMAIN):
        raw.extend(generate_domain_facts(domain, N_PER_CALL, excluded_lower))
        n_calls += 1
    n_generated_raw = len(raw)

    cleaned = [
        c
        for c in raw
        if _clean_candidate(c, excluded_lower, exclude_set, held_out_anchors, profanity, vocab_set)
    ]
    n_after_clean = len(cleaned)

    deduped: list[dict] = []
    seen_this_domain: set[tuple[str, str]] = set()
    for c in cleaned:
        key = (c["word"], c["value"])
        if key not in already_seen and key not in seen_this_domain:
            seen_this_domain.add(key)
            deduped.append(c)
    n_after_dedup = len(deduped)

    accepted: list[dict] = []
    for c in deduped:
        n_calls += 2  # property_ok + specific_ok, isolated
        if quality_filter(c):
            accepted.append(c)

    stats = {
        "domain": domain,
        "n_generated_raw": n_generated_raw,
        "n_after_clean_filter": n_after_clean,
        "n_after_dedup": n_after_dedup,
        "n_accepted_after_judge": len(accepted),
        "n_teacher_calls": n_calls,
    }
    return accepted, stats


# ---------------------------------------------------------------------------
# Step 2: hard-negative mining (rank-band 50-500, hard_negatives.py's exact
# approach, reimplemented in-memory against the OFF-THE-SHELF model -- see
# module docstring's "Hard-negative mining model note").
# ---------------------------------------------------------------------------


def load_off_the_shelf_hien_matrix() -> tuple[list[str], dict[str, int], np.ndarray]:
    """Embed the full hi-en vocab against the OFF-THE-SHELF model once --
    expensive-ish (embeddings.embed_vocab file-caches by content hash per
    its own docstring, so repeat calls across process restarts are cheap
    after the first), so callers that hard-negative-mine multiple domains
    load this ONCE and reuse it rather than re-embedding per domain."""
    vocab = load_hien_vocab()
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    with _model_override(OFF_THE_SHELF_MODEL):
        matrix = embed_vocab(vocab, "hi-en")
    return vocab, word_to_idx, matrix


def mine_hard_negatives_for_candidates(
    candidates: list[dict],
    vocab: list[str] | None = None,
    word_to_idx: dict[str, int] | None = None,
    matrix: np.ndarray | None = None,
) -> tuple[list[dict], dict]:
    """For each accepted (word, value) candidate, mine a rank-band-50-500
    hard negative against the OFF-THE-SHELF hi-en embedding -- identical
    algorithm/constants to hard_negatives.mine_hard_negatives (HARD_NEG_
    RANK_LO/HI, MIN_LEVENSHTEIN imported directly, not re-derived), just
    operating on an in-memory candidate list instead of a JSONL file so
    nothing on disk is touched. Returns (candidates_with_hard_negative,
    stats); candidates with no valid band match are dropped, reported
    honestly. `vocab`/`word_to_idx`/`matrix` may be passed in (see
    `load_off_the_shelf_hien_matrix`) to avoid re-embedding per call; if
    omitted, embeds fresh (self-contained, for standalone use)."""
    exclude_set = build_exclude_set()
    held_out_anchors = held_out_anchor_words()

    if vocab is None or word_to_idx is None or matrix is None:
        vocab, word_to_idx, matrix = load_off_the_shelf_hien_matrix()

    out: list[dict] = []
    n_no_anchor_in_vocab = 0
    n_no_candidate_found = 0
    rank_order_cache: dict[str, np.ndarray] = {}

    for c in candidates:
        anchor = c["word"]
        value = c["value"]
        if anchor not in word_to_idx:
            n_no_anchor_in_vocab += 1
            continue
        if anchor not in rank_order_cache:
            sims = cosine_similarities(matrix, matrix[word_to_idx[anchor]])
            rank_order_cache[anchor] = np.argsort(-sims)
        order = rank_order_cache[anchor]

        candidate_neg = None
        for idx in order[HARD_NEG_RANK_LO : HARD_NEG_RANK_HI + 1]:
            w = vocab[idx]
            wl = w.lower()
            if wl == value.lower() or wl == anchor.lower():
                continue
            if wl in exclude_set or wl in held_out_anchors:
                continue
            if levenshtein(wl, anchor.lower()) < MIN_LEVENSHTEIN:
                continue
            candidate_neg = w
            break
        if candidate_neg is None:
            n_no_candidate_found += 1
            continue
        out.append({**c, "hard_negative": candidate_neg})

    stats = {
        "n_input_candidates": len(candidates),
        "n_output_with_hard_negative": len(out),
        "n_no_anchor_in_vocab": n_no_anchor_in_vocab,
        "n_no_candidate_found": n_no_candidate_found,
        "rank_band": [HARD_NEG_RANK_LO, HARD_NEG_RANK_HI],
        "mined_against": OFF_THE_SHELF_MODEL,
    }
    return out, stats


# ---------------------------------------------------------------------------
# No-leakage verification -- checked programmatically, not assumed.
# ---------------------------------------------------------------------------


def verify_no_leakage(candidates: list[dict]) -> dict:
    """Raises AssertionError with the offending record(s) on any hit. Checks,
    per candidate: (1) `word` is not one of the 8 held-out curated anchors,
    (2) word/value/hard_negative are all clean of build_exclude_set() (60
    schedule secrets both langs, every pack secret every lang, every alias,
    the 34 public-benchmark secrets), (3) `word` is present in the current
    hi-en vocab (guards against a hallucinated non-vocab anchor slipping
    through despite the earlier clean-filter)."""
    exclude_set = build_exclude_set()
    held_out_anchors = held_out_anchor_words()
    vocab_set = set(load_hien_vocab())
    problems: list[str] = []
    for c in candidates:
        if c["word"] in held_out_anchors:
            problems.append(
                f"{c['word']}: is a HELD-OUT curated anchor -- must never be trained on"
            )
        for field in ("word", "value", "hard_negative"):
            val = c[field].lower()
            if val in exclude_set:
                problems.append(f"{c['word']}: field {field!r}={val!r} is in the exclude set")
        if c["word"] not in vocab_set:
            problems.append(f"{c['word']}: not present in current hi-en vocab")
    if problems:
        raise AssertionError("no-leakage / vocab check FAILED:\n" + "\n".join(problems))
    return {
        "n_candidates": len(candidates),
        "n_held_out_anchors": len(held_out_anchors),
        "n_exclude_set": len(exclude_set),
        "passed": True,
    }


# ---------------------------------------------------------------------------
# Step 3: build training records + train
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def build_probe_records(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """One MNRL triplet (anchor=word, positive=value, negative=hard_negative)
    + two graded rows (positive at score 0.85 -- train_lib.TIER_SCORE's
    "near" value, matching how every other strong-associate pair in this
    project's training data is scored; hard negative at score 0.05 --
    "far", matching probe_subword_collision.build_probe_records's identical
    convention) per accepted candidate."""
    new_mnrl = [
        {
            "anchor": c["word"],
            "positive": c["value"],
            "negative": c["hard_negative"],
            "source": RUN_NAME,
        }
        for c in candidates
    ]
    new_graded = []
    for c in candidates:
        new_graded.append(
            {"sentence1": c["word"], "sentence2": c["value"], "score": 0.85, "source": RUN_NAME}
        )
        new_graded.append(
            {
                "sentence1": c["word"],
                "sentence2": c["hard_negative"],
                "score": 0.05,
                "source": RUN_NAME,
            }
        )
    return new_mnrl, new_graded


def build_extended_training_set(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """The obj_hard_neg base training set (train_mnrl_pairs_hard_neg.jsonl +
    train_graded_pairs.jsonl -- the exact files the SHIPPED model trained
    on) extended in-memory with this probe's new records. Never writes to
    disk -- same pattern as probe_subword_collision.py's function of the
    same name."""
    base_mnrl = _load_jsonl(DATA_DIR / "train_mnrl_pairs_hard_neg.jsonl")
    base_graded = _load_jsonl(DATA_DIR / "train_graded_pairs.jsonl")
    new_mnrl, new_graded = build_probe_records(candidates)
    return base_mnrl + new_mnrl, base_graded + new_graded


def _read_existing_pairs_file() -> list[dict]:
    if not PAIRS_OUT_PATH.exists():
        return []
    return _load_jsonl(PAIRS_OUT_PATH)


def _append_pairs_file(new_records: list[dict]) -> None:
    PAIRS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PAIRS_OUT_PATH.open("a", encoding="utf-8") as f:
        for c in new_records:
            f.write(json.dumps(c) + "\n")


def mine_and_save_pairs(
    domains: list[str] | None = None, fresh: bool = False
) -> tuple[list[dict], dict]:
    """Step-1+2 pipeline, run DOMAIN-BY-DOMAIN with INCREMENTAL persistence:
    each domain's generate -> clean -> dedup -> judge-filter -> hard-neg-mine
    result is appended to PAIRS_OUT_PATH as soon as that domain finishes,
    rather than only at the very end. This environment ran under sustained,
    bursty GPU contention from concurrent unrelated processes (see module
    docstring's DEVIATION note) that repeatedly killed long-running
    background invocations before a single "write once at the end" pass
    could complete -- incremental persistence means a killed run's earlier
    domains are never lost, and re-invoking (this function is naturally
    resumable -- `already_seen` dedup is keyed off whatever's already on
    disk) picks up where it left off rather than restarting from zero.

    `fresh=True` truncates PAIRS_OUT_PATH first (start over); default
    (False) APPENDS to and dedupes against whatever's already there.
    `domains` restricts to a subset of DOMAINS (for resuming just the
    domains that failed in a prior invocation); default is all of DOMAINS.
    """
    if fresh and PAIRS_OUT_PATH.exists():
        PAIRS_OUT_PATH.unlink()

    exclude_set = build_exclude_set()
    held_out_anchors = held_out_anchor_words()
    excluded_lower = held_out_anchors | exclude_set
    profanity = load_en_profanity() | load_hi_profanity()
    vocab_set = set(load_hien_vocab())

    existing = _read_existing_pairs_file()
    already_seen = {(c["word"], c["value"]) for c in existing}
    vocab, word_to_idx, matrix = load_off_the_shelf_hien_matrix()

    per_domain_stats: dict[str, dict] = {}
    all_new: list[dict] = []
    for domain in domains or DOMAINS:
        accepted, gen_stats = generate_and_filter_domain(
            domain, excluded_lower, exclude_set, held_out_anchors, profanity, vocab_set,
            already_seen,
        )
        with_neg, mine_stats = mine_hard_negatives_for_candidates(
            accepted, vocab=vocab, word_to_idx=word_to_idx, matrix=matrix
        )
        verify_no_leakage(with_neg)  # raise immediately, never persist a leak
        _append_pairs_file(with_neg)
        already_seen |= {(c["word"], c["value"]) for c in with_neg}
        all_new.extend(with_neg)
        per_domain_stats[domain] = {"generation": gen_stats, "hard_neg_mining": mine_stats}
        print(
            f"--- domain {domain!r}: {gen_stats['n_accepted_after_judge']} judge-accepted, "
            f"{len(with_neg)} with hard negative (appended to {PAIRS_OUT_PATH}) ---"
        )

    final_pairs = _read_existing_pairs_file()
    by_domain: dict[str, int] = {}
    for c in final_pairs:
        by_domain[c["domain"]] = by_domain.get(c["domain"], 0) + 1

    stats = {
        "teacher_model": TEACHER_MODEL,
        "n_new_this_run": len(all_new),
        "n_total_on_disk": len(final_pairs),
        "domain_breakdown_total": by_domain,
        "per_domain_this_run": per_domain_stats,
        "no_leakage_check": verify_no_leakage(final_pairs),
    }
    print(json.dumps(stats, indent=2))
    print(f"{len(final_pairs)} total mined pairs on disk at {PAIRS_OUT_PATH}")
    return final_pairs, stats


def load_mined_pairs() -> list[dict]:
    if not PAIRS_OUT_PATH.exists():
        raise FileNotFoundError(
            f"{PAIRS_OUT_PATH} not found -- run --generate first "
            "(uv run python -m evals.finetune.probe_lever_l6_commonsense_data --generate)"
        )
    return _load_jsonl(PAIRS_OUT_PATH)


def train_probe() -> dict:
    candidates = load_mined_pairs()
    verify_no_leakage(candidates)  # re-checked, never trusted from a prior run alone

    extended_mnrl, extended_graded = build_extended_training_set(candidates)
    print(
        f"extended training set: {len(extended_mnrl)} mnrl "
        f"(base {len(extended_mnrl) - len(candidates)} + {len(candidates)} new), "
        f"{len(extended_graded)} graded "
        f"(base {len(extended_graded) - 2 * len(candidates)} + {2 * len(candidates)} new)"
    )

    cfg = TrainConfig(
        name=RUN_NAME,
        method="lora",
        lora_r=8,
        lora_alpha=16,
        learning_rate=2e-4,
        num_epochs=4,
        early_stopping_patience=2,
        seed=42,
        mnrl_records=extended_mnrl,
        graded_records=extended_graded,
    )
    t0 = time.monotonic()
    summary = run_training(cfg)
    summary["_wall_clock_s"] = time.monotonic() - t0
    print(json.dumps({k: v for k, v in summary.items() if k != "dev_curve"}, indent=2))
    return summary


# ---------------------------------------------------------------------------
# Step 4a: generalization check on the 8 HELD-OUT curated words.
# ---------------------------------------------------------------------------

_BAND_NAMES = {0: "win", 1: "scorching", 2: "hot", 3: "warm", 4: "cold", 5: "freezing"}


def _held_out_rank_report(model_name_or_path: str, held_out: list[dict]) -> dict:
    """For every held-out curated (word, related) pair, the `related`
    word's rank against `word` under `model_name_or_path`, computed via
    probe_lever_l5_rank_override.compute_ranks (the exact rank algorithm
    payload._build_payload_core uses, reused not reimplemented)."""
    from rival import band_for_rank

    vocab = load_hien_vocab()
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    n = len(vocab)
    with _model_override(model_name_or_path):
        matrix = embed_vocab(vocab, "hi-en")
    assert matrix.shape[0] == n, (
        f"embedding matrix rows ({matrix.shape[0]}) != vocab length ({n}) for "
        f"{model_name_or_path!r} -- cache/vocab mismatch"
    )

    out = {}
    for cand in held_out:
        secret, related = cand["word"], cand["related"]
        assert secret in word_to_idx, f"{secret!r} not in current hi-en vocab"
        assert related in word_to_idx, f"{related!r} not in current hi-en vocab"
        ranks = compute_ranks(matrix, word_to_idx[secret])
        rank = int(ranks[word_to_idx[related]])
        out[secret] = {
            "related": related,
            "rank": rank,
            "rank_percentile": round(100 * rank / n, 2),
            "band_ordinal": band_for_rank(rank, n),
            "band_name": _BAND_NAMES[band_for_rank(rank, n)],
        }
    return out


def generalization_check(probe_model_path: str) -> dict:
    """THE key L6 question: before (shipped model) -> after (probe
    checkpoint) rank movement for all 8 held-out curated words, none of
    which were ever in this probe's training set."""
    held_out = load_held_out_candidates()
    before = _held_out_rank_report(SHIPPED_MODEL, held_out)
    after = _held_out_rank_report(probe_model_path, held_out)

    per_word = []
    n_improved = 0
    n_regressed = 0
    for cand in held_out:
        w = cand["word"]
        b, a = before[w], after[w]
        delta = b["rank"] - a["rank"]  # positive = rank improved (lower rank number)
        if delta > 0:
            n_improved += 1
        elif delta < 0:
            n_regressed += 1
        per_word.append(
            {
                "word": w,
                "gloss": cand["gloss"],
                "related": cand["related"],
                "related_gloss": cand["related_gloss"],
                "recorded_related_rank_at_curation": cand["related_rank"],
                "before_shipped": b,
                "after_probe": a,
                "rank_delta": delta,
                "band_delta": b["band_ordinal"] - a["band_ordinal"],
            }
        )
    return {
        "probe_model_path": probe_model_path,
        "shipped_model": SHIPPED_MODEL,
        "n_held_out_words": len(held_out),
        "n_rank_improved": n_improved,
        "n_rank_regressed": n_regressed,
        "n_rank_unchanged": len(held_out) - n_improved - n_regressed,
        "per_word": per_word,
    }


# ---------------------------------------------------------------------------
# Step 4b: full-34 public-benchmark regression floor -- reuses probe_subword_
# collision.py's exact comparator functions (same functions probe_lever_l1_
# capacity.py reuses) for apples-to-apples comparability across this wave.
# ---------------------------------------------------------------------------


def benchmark_regression_check(probe_model_path: str) -> dict:
    probe_dim1 = _public_benchmark_dim1_records(probe_model_path)
    probe_dim2 = _public_benchmark_dim2_result(probe_model_path)

    shipped_dim1 = _shipped_model_dim1_records_34()
    shipped_dim2 = _shipped_model_dim2_records_34()

    probe_dim1_ci = bootstrap_dim1_spearman_ci(probe_dim1)
    probe_dim2_ci = bootstrap_dim2_pass_rate_ci(probe_dim2["records"])
    shipped_dim1_ci = bootstrap_dim1_spearman_ci(shipped_dim1)
    shipped_dim2_ci = bootstrap_dim2_pass_rate_ci(shipped_dim2)

    dim1_delta = paired_bootstrap_dim1_delta(shipped_dim1, probe_dim1)
    dim2_delta = paired_bootstrap_dim2_delta(shipped_dim2, probe_dim2["records"])

    by_tier = {t: [r for r in probe_dim1 if r["tier"] == t] for t in ("near", "mid", "far")}
    probe_band_accuracy = {
        "overall": _band_accuracy(probe_dim1),
        "near": _band_accuracy(by_tier["near"]),
        "mid": _band_accuracy(by_tier["mid"]),
        "far": _band_accuracy(by_tier["far"]),
    }

    shipped_pass = {r["hien_secret"]: r["consistent"] for r in shipped_dim2}
    probe_pass = {r["hien_secret"]: r["consistent"] for r in probe_dim2["records"]}
    common_secrets = sorted(set(shipped_pass) & set(probe_pass))
    newly_broken = [
        s for s in common_secrets if shipped_pass[s] is True and probe_pass[s] is not True
    ]
    newly_fixed = [
        s for s in common_secrets if shipped_pass[s] is not True and probe_pass[s] is True
    ]

    return {
        "model_path": probe_model_path,
        "n_dim1_secrets": len({r["secret"] for r in probe_dim1}),
        "n_dim1_scenarios": len(probe_dim1),
        "n_dim2_pairs": len(probe_dim2["records"]),
        "probe_dim1_spearman_ci": probe_dim1_ci,
        "probe_dim2_pass_rate_ci": probe_dim2_ci,
        "shipped_dim1_spearman_ci": shipped_dim1_ci,
        "shipped_dim2_pass_rate_ci": shipped_dim2_ci,
        "probe_band_accuracy": probe_band_accuracy,
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim2_regression_floor": {
            "n_common_secrets": len(common_secrets),
            "n_newly_broken": len(newly_broken),
            "newly_broken": newly_broken,
            "n_newly_fixed": len(newly_fixed),
            "newly_fixed": newly_fixed,
        },
    }


def evaluate_probe(model_path: str | None = None) -> dict:
    if model_path is None:
        summary_path = DATA_DIR / "runs" / f"{RUN_NAME}.train_summary.json"
        model_path = json.loads(summary_path.read_text(encoding="utf-8"))["output_dir"]

    t0 = time.monotonic()
    generalization = generalization_check(model_path)
    benchmark = benchmark_regression_check(model_path)
    wall_clock_s = time.monotonic() - t0

    mined = load_mined_pairs() if PAIRS_OUT_PATH.exists() else []
    by_domain: dict[str, int] = {}
    for c in mined:
        by_domain[c["domain"]] = by_domain.get(c["domain"], 0) + 1

    result = {
        "run_name": RUN_NAME,
        "spec_ref": "spec-residual-attack.md lever L6",
        "teacher_model": TEACHER_MODEL,
        "n_training_pairs_mined": len(mined),
        "training_domain_breakdown": by_domain,
        "generalization_check_held_out_8_words": generalization,
        "benchmark_regression_floor": benchmark,
        "_eval_wall_clock_s": wall_clock_s,
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {RESULT_PATH}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate", action="store_true", help="mine/generate + judge-filter commonsense pairs"
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        default=None,
        choices=DOMAINS,
        help="restrict --generate to a subset of DOMAINS (for resuming a partial run)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="--generate: truncate PAIRS_OUT_PATH first instead of resuming/appending",
    )
    parser.add_argument("--train", action="store_true", help="run the probe fine-tune")
    parser.add_argument("--eval", action="store_true", help="evaluate the trained probe checkpoint")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="only run no-leakage checks against already-mined pairs, no generation/train/eval",
    )
    args = parser.parse_args()

    if args.check_only:
        print(json.dumps(verify_no_leakage(load_mined_pairs()), indent=2))
        return

    if not (args.generate or args.train or args.eval):
        parser.print_help()
        return

    if args.generate:
        mine_and_save_pairs(domains=args.domains, fresh=args.fresh)
    if args.train:
        train_probe()
    if args.eval:
        evaluate_probe()


if __name__ == "__main__":
    main()
