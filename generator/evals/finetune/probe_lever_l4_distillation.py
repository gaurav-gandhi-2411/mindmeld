from __future__ import annotations

"""
Cheap probe for lever L4 (spec-residual-attack.md): targeted knowledge
DISTILLATION for the "associative-commonsense" residual mechanism (docs/
known-limitations.md entry 20) -- world-knowledge facts (taste, color,
texture, sound) that are NOT derivable from text co-occurrence alone (e.g.
tarbooz/watermelon's flesh is red -- known from cutting one open, not from
reading text). This is a DIFFERENT residual mechanism from the subword-
collision one probe_subword_collision.py/probe_lever_l1_capacity.py attack
(junoon/registan-class); PROVEN DEAD there was "more hard negatives at the
same LoRA rank" -- that finding does not transfer here, since this residual's
root cause (missing world-knowledge signal, not a corrupted input embedding)
is structurally different.

Method: a large instruction-tuned local LLM (teacher) KNOWS these property
facts. Distill that signal directly into the student embedding model by
training toward TEACHER-VERIFIED, TEACHER-GRADED targets for 8 curated,
no-leakage-verified candidates (data/commonsense_residual_candidates.json,
curated by a prior agent with per-candidate justification -- read-only here).

Stage 1 -- teacher generation/verification, THREE ISOLATED calls per
candidate (this repo's own documented finding, PLAN.md: isolated judge calls
calibrate far better than compound self-judging -- one fact/one score per
call, never bundled):
  (a) fact_check(word, related)   -- isolated true/false judge: is the
      property genuinely true/salient for this word, from real-world
      experience, not text co-occurrence?
  (b) score(word, related)        -- isolated graded relatedness score in
      [0, 1] -- the actual DISTILLATION target (not a binary filter).
  (c) score(word, hard_negative)  -- isolated graded relatedness score in
      [0, 1] for the plausible-but-wrong distractor (expected low/moderate,
      not near-zero, since it's a genuine distractor from the same domain,
      not a random unrelated word).
Local Ollama, same protocol as llm_augment.py's `_call_ollama` (JSON-schema
`format`, temperature 0.2). DOCUMENTED DEVIATION (mirrors probe_lever_l2_
devanagari_hybrid.py's precedent exactly): qwen3:8b is NOT pulled in this
environment (verified via /api/tags at probe time -- only llama3.1:8b and
gemma2:9b are available), so `resolve_teacher_model()` falls back to
llama3.1:8b, tagging every teacher record with the actual model used. If NO
Ollama model is reachable at all, this probe reports that blocker honestly
in its eval_result.json and aborts training -- it never fabricates a score.

Stage 2 -- training records built from the teacher's ACTUAL scores (not a
fixed constant): one MNRL triplet (anchor=word, positive=related,
negative=hard_negative) plus TWO graded pairs per candidate (word/related at
the teacher's score_related, word/hard_negative at the teacher's
score_hard_negative) -- schema matches train_graded_pairs.jsonl exactly
(sentence1/sentence2/score/source, verified by reading the file directly).
8 candidates -> 8 new MNRL + 16 new graded records, added IN-MEMORY to the
exact base training set the shipped "obj_hard_neg" model trained on
(train_mnrl_pairs_hard_neg.jsonl + train_graded_pairs.jsonl), following
probe_subword_collision.py's `build_extended_training_set` pattern exactly
-- never written to disk.

Stage 3 -- train one LoRA probe checkpoint with the proven obj_hard_neg
recipe (r=8/alpha=16/lr=2e-4/4 epochs/early_stopping_patience=2/seed=42),
via train_lib.run_training(TrainConfig(...)).

GPU-contention guard (documented, reversible, zero blast radius): at probe
time this machine's single GPU was ~100% utilized / ~7.9 of 8.0 GiB used by
an UNRELATED external process (a different conda env's python.exe, not this
project) -- likely a concurrent session on another local project. Rather
than risk a CUDA OOM mid-run or contend for/kill someone else's GPU work
(out of scope), this module checks free VRAM via `nvidia-smi` at import time
and forces CPU-only training (`CUDA_VISIBLE_DEVICES=""`, set BEFORE the
torch-importing modules below are imported) when free VRAM is below a small
safety threshold. This is transparent and reported in the eval_result.json's
`forced_cpu_training` field -- it changes wall-clock time, not correctness
(LoRA trains ~295k parameters on ~2.7k records either way).

Stage 4 -- evaluate:
  (a) TARGETED check: for each of the 8 words, recompute the `related`
      word's full-vocab rank (10495-word hi-en vocab, same tooling the
      curation agent used -- vocab.load_hien_vocab + embeddings.embed_vocab
      + embeddings.cosine_similarities) under the SHIPPED model (before) and
      the new probe checkpoint (after). The candidates file's own
      `related_rank` field (computed by the curation agent under the shipped
      model) is cross-checked against this probe's independently-recomputed
      "before" rank as a sanity check, not blindly trusted.
  (b) FULL-BENCHMARK regression floor (non-negotiable, universal ruler):
      frozen public 34-secret benchmark (data/public_benchmark_staging/
      dim1_hien.json + dim2_pairs.json), scored via probe_subword_
      collision.py's exact `_public_benchmark_dim1_records`/
      `_public_benchmark_dim2_result` (reused, not duplicated), paired
      bootstrap vs the shipped model's cached bakeoff_raw checkpoint
      (bootstrap_ci.py), and regression.py's `dim1_regression_floor`/
      `dim2_regression_floor` -- matching probe_lever_l2_devanagari_
      hybrid.py's metric-computation calls exactly (the more complete of
      the two prior lever probes: it computes BOTH dim1 and dim2 floors,
      whereas probe_subword_collision.py/probe_lever_l1_capacity.py only
      inline a dim2-only newly-broken/newly-fixed check) -- chosen for
      apples-to-apples comparability across this wave's final comparison
      table.
  (c) OVERFITTING FLAG (spec risk section, explicit, not glossed over): this
      probe trains DIRECTLY on the 8 target words' own (anchor, related,
      hard_negative) pairs. A large rank improvement on them is EXPECTED
      from direct training-set exposure and is NOT evidence the distillation
      APPROACH generalizes to held-out commonsense words never seen in
      training -- that generalization question is lever L6's job (a
      DIFFERENT, separately-run probe against held-out commonsense words),
      not duplicated here.

Run (from generator/):
    uv run python -m evals.finetune.probe_lever_l4_distillation --check-only
    uv run python -m evals.finetune.probe_lever_l4_distillation --teacher
    uv run python -m evals.finetune.probe_lever_l4_distillation --train
    uv run python -m evals.finetune.probe_lever_l4_distillation --eval
"""

import json
import logging
import os
import random
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
STAGING_DIR = DATA_DIR / "public_benchmark_staging"
CANDIDATES_PATH = DATA_DIR / "commonsense_residual_candidates.json"
RUN_NAME = "probe_lever_l4_distillation"

SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"

# ---------------------------------------------------------------------------
# GPU-contention guard -- MUST run before any torch-importing module below is
# imported (train_lib.py, and transitively probe_subword_collision.py, both
# `import torch`). See module docstring's "GPU-contention guard" section.
# ---------------------------------------------------------------------------

_GPU_FREE_MIB_THRESHOLD = 1500  # a ~240M-param BERT LoRA fine-tune's activations +
# optimizer state need meaningful headroom beyond the base model's footprint; below
# this the run risks a CUDA OOM under contention from an unrelated external process.


def _gpu_free_mib() -> int | None:
    """Free VRAM in MiB on GPU 0, or None if `nvidia-smi` is unavailable/errors
    (e.g. no GPU present) -- never assumed, always queried."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return int(out.stdout.strip().splitlines()[0])
    except (FileNotFoundError, subprocess.SubprocessError, ValueError, IndexError):
        return None


_free_mib = _gpu_free_mib()
FORCED_CPU_TRAINING = _free_mib is not None and _free_mib < _GPU_FREE_MIB_THRESHOLD
if FORCED_CPU_TRAINING:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    print(
        f"GPU has only {_free_mib}MiB free (< {_GPU_FREE_MIB_THRESHOLD}MiB threshold) -- "
        "forcing CPU-only training for this run (documented, reversible; see module "
        "docstring's GPU-contention guard section)."
    )

# ---------------------------------------------------------------------------
# Everything below this line may safely import torch.
# ---------------------------------------------------------------------------

from embeddings import cosine_similarities, embed_vocab  # noqa: E402
from evals.finetune.bootstrap_ci import (  # noqa: E402
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import _model_override  # noqa: E402
from evals.finetune.llm_augment import LLMUnavailableError  # noqa: E402
from evals.finetune.probe_subword_collision import (  # noqa: E402
    PUBLIC_BENCHMARK_34_SECRETS,  # noqa: F401  (re-exported for callers/tests)
    _public_benchmark_dim1_records,
    _public_benchmark_dim2_result,
    _shipped_model_dim1_records_34,
    _shipped_model_dim2_records_34,
    build_exclude_set,
)
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor  # noqa: E402
from evals.finetune.train_lib import TrainConfig, run_training  # noqa: E402
from vocab import load_hien_vocab  # noqa: E402

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
PRIMARY_TEACHER_MODEL = "qwen3:8b"
FALLBACK_TEACHER_MODEL = "llama3.1:8b"
TIMEOUT_SECONDS = 300  # first call pays Ollama's cold-load cost (observed ~207s under
# GPU contention at probe time); subsequent calls with the model already resident are
# sub-second -- generous ceiling, not a typical per-call latency.

_FACT_CHECK_SCHEMA = {
    "type": "object",
    "properties": {"fact_true": {"type": "boolean"}},
    "required": ["fact_true"],
}
_SCORE_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "number"}},
    "required": ["score"],
}


# NARROWED to SENSORY/PERCEPTUAL properties only (taste, color, texture, sound), and explicitly
# EXCLUDES functional/production/co-occurrence links (e.g. "produces", "made from", "used to
# make") -- this is a deliberate root-cause fix, not the original wording. An earlier version of
# _SCORE_PROMPT asked for general "real-world/commonsense relatedness ... including ...
# functional associations", which let til/kala (0.5, the curated SENSORY property -- black
# sesame seeds) score LOWER than til/tel (0.8, the curated hard negative) because "til ka tel"/
# sesame OIL is an extremely tight FUNCTIONAL/production collocation that the base embedding
# already captures well (til's own top-15 neighbors already rank "tel" #1 and "seeds" #6, per
# commonsense_residual_candidates.json's own justification) -- i.e. the broad prompt let the
# teacher reward exactly the kind of co-occurrence-derivable relatedness this lever is NOT
# trying to distill (spec-residual-attack.md's L4 targets world-knowledge SENSORY properties
# specifically, "known from tasting/seeing, not reading"). Every `related` word across all 8
# candidates (lal/red, safed/white, garm/hot, kala/black, loud) is a genuine sensory-property
# adjective; every `hard_negative` (pyaaz/onion, adrak/ginger, peanut, sauce, dalchini/cinnamon,
# foliage, tel/oil, syrup) is a co-occurring THING noun, not itself a sensory property -- so a
# prompt that scores STRICTLY "is this a taste/color/texture/sound property" (not general
# relatedness) should structurally favor every curated `related` over every curated
# `hard_negative`, which is the invariant the caller validates and self-repairs against below
# (see `validate_and_repair_teacher_scores`).
_FACT_CHECK_PROMPT = """In real-world commonsense terms (not text co-occurrence, not \
production/functional links like "produces" or "made from"), is it TRUE and SALIENT that \
"{word}" ({gloss}) has the SENSORY/PERCEPTUAL property "{related}" ({related_gloss}) -- \
specifically its taste, color, texture, or sound, known from directly tasting, seeing, \
touching, or hearing it, not just from reading about it? Answer strictly -- if the connection \
is only partial, weak, functional-but-not-sensory, or not how most people would describe it, \
say false.

Respond with ONLY: {{"fact_true": <true|false>}}"""

_SCORE_PROMPT = """You are scoring SENSORY/PERCEPTUAL commonsense relatedness ONLY -- the kind \
of property fact a person knows from directly tasting, seeing, touching, or hearing something, \
NOT from reading about it and NOT a functional/production/co-occurrence link (e.g. "produces", \
"made from", "used to make", "found together with" do NOT count, even if true).

On a scale from 0.0 (no sensory/perceptual relationship at all) to 1.0 (a defining, essential \
sensory property), how strongly is "{word}" ({gloss}) related to "{other}" ({other_gloss}) \
specifically as a TASTE, COLOR, TEXTURE, or SOUND property? If "{other}" is not itself a \
sensory-property word (e.g. it names a different object/ingredient rather than a taste, color, \
texture, or sound), score it low even if the two words are otherwise commonly associated.

Respond with ONLY: {{"score": <float between 0.0 and 1.0>}}"""


# ---------------------------------------------------------------------------
# Step 0: candidates (read-only) + no-leakage verification.
# ---------------------------------------------------------------------------


def load_candidates() -> list[dict]:
    return json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))


def verify_no_leakage(candidates: list[dict]) -> dict:
    """Verify every candidate's `word`/`related`/`hard_negative` (the only
    fields ever used as an anchor/target -- `*_gloss` fields are human-
    readable English documentation, not embedded/ranked, and are not in the
    hi-en vocab, e.g. "watermelon"/"pomegranate"/"sesame" -- verified
    directly, not assumed) is clean of the full no-fly list AND present in
    the hi-en vocab. Reuses probe_subword_collision.build_exclude_set()
    verbatim (same 60 daily-schedule secrets + every pack secret + the 34
    public-benchmark secrets, both langs + aliases). Raises AssertionError
    with the offending word(s) on any hit -- never silently skips a leak."""
    exclude = build_exclude_set()
    vocab = set(load_hien_vocab())
    problems: list[str] = []
    for c in candidates:
        for field in ("word", "related", "hard_negative"):
            val = c[field].lower()
            if val in exclude:
                problems.append(f"{c['word']}: field {field!r}={val!r} is in the exclude set")
            if val not in vocab:
                problems.append(f"{c['word']}: field {field!r}={val!r} is NOT in hi-en vocab")
    if problems:
        raise AssertionError("no-leakage / vocab check FAILED:\n" + "\n".join(problems))
    return {
        "n_candidates": len(candidates),
        "n_exclude_set": len(exclude),
        "passed": True,
    }


# ---------------------------------------------------------------------------
# Step 1: teacher generation/verification -- three ISOLATED Ollama calls per
# candidate (fact_check, score(word,related), score(word,hard_negative)).
# ---------------------------------------------------------------------------


def check_ollama_up() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def _model_available(model: str) -> bool:
    """True iff `model` is present in the local Ollama server's tag list --
    checked directly, never assumed (mirrors probe_lever_l2_devanagari_
    hybrid.py's `check_ollama_up` liveness-check discipline, extended to
    per-model availability since the server can be up with the wrong model
    pulled, per probe time's observed {"error": "model 'qwen3:8b' not
    found"} response -- an HTTP 200 with an error body, not a URLError)."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:  # noqa: S310
            tags = json.loads(resp.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
        return False
    return any(m.get("name") == model for m in tags.get("models", []))


_LIVENESS_PROBE_TIMEOUT_S = 20  # short bound -- distinguishes "pulled but the shared Ollama
# server is too contended to actually serve it right now" from a real cold-load (which the
# real calls' own warm-up + retry logic separately tolerates, see `_warm_up_teacher_model`).


def _model_responds(model: str, timeout: int = _LIVENESS_PROBE_TIMEOUT_S) -> bool:
    """True iff `model` answers ONE tiny throwaway call within `timeout`
    seconds -- a real liveness check, not just tag-list membership. This
    Ollama server is observably SHARED with other concurrently-running
    lever probes in this wave (its `/api/tags` grew from 2 models to 7
    over the course of this single probe run, including qwen3:8b appearing
    mid-run) -- a model can be *pulled* yet consistently time out under
    that contention (confirmed at probe time: a bare `curl -m 25` to
    qwen3:8b returned nothing in 25s while llama3.1:8b answered
    sub-second). No retry here by design -- a single failed probe is
    already sufficient signal to prefer the empirically-working fallback
    rather than burn the real calls' retry budget against an overloaded
    model."""
    try:
        _call_ollama_model(
            'Respond with ONLY: {"fact_true": true}',
            model,
            _FACT_CHECK_SCHEMA,
            timeout=timeout,
            max_attempts=1,
        )
        return True
    except (LLMUnavailableError, json.JSONDecodeError):
        return False


def resolve_teacher_model() -> tuple[str | None, str]:
    """Resolve the teacher model: PRIMARY_TEACHER_MODEL if pulled AND it
    actually responds within a short liveness probe, else
    FALLBACK_TEACHER_MODEL if pulled (DOCUMENTED DEVIATION, mirrors probe_
    lever_l2_devanagari_hybrid.py's qwen3:8b->llama3.1:8b precedent, and
    extends it: at probe time qwen3:8b was first not pulled at all, then
    later appeared pulled by a different concurrent agent sharing this
    Ollama server but was empirically unresponsive under that contention --
    see `_model_responds`'s docstring). Returns (model_name_or_None,
    reason) -- model is None only if Ollama is fully unreachable or
    neither model is pulled/responsive, in which case `reason` explains
    why (never fabricated)."""
    if not check_ollama_up():
        return None, f"Ollama unreachable at {OLLAMA_TAGS_URL}"
    if _model_available(PRIMARY_TEACHER_MODEL) and _model_responds(PRIMARY_TEACHER_MODEL):
        return PRIMARY_TEACHER_MODEL, "primary model available and responsive"
    if _model_available(FALLBACK_TEACHER_MODEL):
        return (
            FALLBACK_TEACHER_MODEL,
            f"DEVIATION: {PRIMARY_TEACHER_MODEL} not pulled, or pulled but did not respond "
            f"within {_LIVENESS_PROBE_TIMEOUT_S}s under this shared Ollama server's current "
            f"contention (verified via /api/tags + a live liveness probe, not assumed) -- "
            f"fell back to {FALLBACK_TEACHER_MODEL}, same protocol as probe_lever_l2_"
            "devanagari_hybrid.py's documented precedent",
        )
    return None, f"neither {PRIMARY_TEACHER_MODEL} nor {FALLBACK_TEACHER_MODEL} is pulled"


_MAX_RETRIES = 3
_RETRY_BASE_DELAY_S = 3.0


def _call_ollama_model(
    prompt: str,
    model: str,
    response_format: dict,
    timeout: int = TIMEOUT_SECONDS,
    max_attempts: int = _MAX_RETRIES,
) -> dict:
    """Same wire protocol as llm_augment.py's `_call_ollama` (JSON-schema
    `format`, temperature 0.2), parameterized on `model` since llm_augment's
    version hardcodes MODEL="qwen3:8b" (unavailable here -- see
    `resolve_teacher_model`). `keep_alive` is set generously so the model
    stays resident in VRAM across this probe's ~24 isolated calls instead of
    reloading (observed ~207s cold-load time at probe time).

    Retries with backoff+jitter on transient connection failures (rule 108
    -- every outbound call gets a timeout + retry): this Ollama server is
    observably SHARED across other lever probes running concurrently in
    this same wave (a `qwen2.5vl:7b` model neither this probe nor its
    documented fallback ever requests appeared in `/api/tags` mid-run --
    evidence of a different concurrent agent), and an initial run of this
    exact call hit `WinError 10061 connection refused` /
    `WinError 10054 forcibly closed` on 4 of 24 calls, consistent with
    transient contention rather than a real outage. Does NOT retry on a
    clean {"error": ...} response body (that is a real, stable condition --
    e.g. model not pulled -- retrying would not help)."""
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": response_format,
            "options": {"temperature": 0.2},
            "keep_alive": "10m",
        }
    ).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        request = urllib.request.Request(
            OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                outer = json.loads(response.read())
            break
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = _RETRY_BASE_DELAY_S * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "ollama call failed (attempt %d/%d, model=%s): %s -- retrying in %.1fs",
                    attempt + 1,
                    max_attempts,
                    model,
                    e,
                    delay,
                )
                time.sleep(delay)
    else:
        raise LLMUnavailableError(
            f"could not reach local Ollama at {OLLAMA_URL} (model={model}) after "
            f"{max_attempts} attempts: {last_error}"
        ) from last_error
    if "error" in outer:
        raise LLMUnavailableError(f"ollama model={model!r} returned error: {outer['error']!r}")
    raw = outer.get("response", "")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("expected a JSON object", raw, 0)
    return parsed


def teacher_fact_check(word: str, gloss: str, related: str, related_gloss: str, model: str) -> bool | None:
    """Isolated judge call #1: is the curated property fact genuinely true/
    salient? Returns None (never a fabricated bool) on any call failure."""
    prompt = _FACT_CHECK_PROMPT.format(
        word=word, gloss=gloss, related=related, related_gloss=related_gloss
    )
    try:
        resp = _call_ollama_model(prompt, model, _FACT_CHECK_SCHEMA)
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("fact_check failed for word=%r related=%r: %s", word, related, e)
        return None
    val = resp.get("fact_true")
    return val if isinstance(val, bool) else None


def teacher_score(word: str, gloss: str, other: str, other_gloss: str, model: str) -> float | None:
    """Isolated graded-relatedness call: returns a float clamped to [0, 1],
    or None (never fabricated) on any call failure or non-numeric response."""
    prompt = _SCORE_PROMPT.format(word=word, gloss=gloss, other=other, other_gloss=other_gloss)
    try:
        resp = _call_ollama_model(prompt, model, _SCORE_SCHEMA)
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("score failed for word=%r other=%r: %s", word, other, e)
        return None
    val = resp.get("score")
    if not isinstance(val, int | float) or isinstance(val, bool):
        return None
    return max(0.0, min(1.0, float(val)))


def score_candidate(candidate: dict, model: str) -> dict:
    """Three isolated teacher calls for one candidate; returns the full
    teacher record (never silently drops a failed field -- None propagates
    and is checked by the caller before training)."""
    fact_true = teacher_fact_check(
        candidate["word"], candidate["gloss"], candidate["related"], candidate["related_gloss"], model
    )
    score_related = teacher_score(
        candidate["word"], candidate["gloss"], candidate["related"], candidate["related_gloss"], model
    )
    score_hard_negative = teacher_score(
        candidate["word"],
        candidate["gloss"],
        candidate["hard_negative"],
        candidate["hard_negative_gloss"],
        model,
    )
    return {
        "word": candidate["word"],
        "gloss": candidate["gloss"],
        "related": candidate["related"],
        "related_gloss": candidate["related_gloss"],
        "hard_negative": candidate["hard_negative"],
        "hard_negative_gloss": candidate["hard_negative_gloss"],
        "teacher_model": model,
        "fact_true": fact_true,
        "score_related": score_related,
        "score_hard_negative": score_hard_negative,
    }


def _warm_up_teacher_model(model: str) -> None:
    """Best-effort readiness probe: one throwaway isolated call with a long
    timeout, sent BEFORE the real 24 scoring calls, to force Ollama to
    finish loading `model` into memory outside the real calls' retry
    budget. Root-cause fix for an observed failure mode: this probe's
    retry backoff (a handful of attempts, seconds-to-tens-of-seconds each)
    is sized for TRANSIENT contention blips from other concurrently-
    running agents sharing this Ollama server, not a full ~200s+ cold
    model load -- at probe time, `tarbooz`'s two `teacher_score` calls
    landed exactly during a cold-load window and exhausted their retries,
    leaving `score_related`/`score_hard_negative` null. Failure here is
    non-fatal (falls through to the real calls' own retry logic) -- this
    is a best-effort warm-up, not a hard precondition."""
    try:
        _call_ollama_model(
            'Respond with ONLY: {"fact_true": true}', model, _FACT_CHECK_SCHEMA, timeout=280
        )
        print(f"  teacher model {model!r} warm-up call succeeded")
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("teacher model warm-up call failed (non-fatal, continuing): %s", e)
        print(f"  teacher model {model!r} warm-up call failed (non-fatal): {e}")


def validate_teacher_record(rec: dict) -> list[str]:
    """Problems with `rec`, empty list = valid. `fact_true` is a separate
    isolated finding (module docstring point (a)) and is NOT a training-
    blocking gate here -- but `score_related`/`score_hard_negative` (point
    (b)/(c), the actual distillation targets) must both be non-null AND
    `score_related` must be STRICTLY GREATER than `score_hard_negative`:
    every hard_negative was curated specifically to be a plausible-but-
    wrong distractor (commonsense_residual_candidates.json), so a graded
    training pair where the "wrong" distractor outscores the true property
    would corrupt the distillation target, not just look odd."""
    problems: list[str] = []
    if rec["score_related"] is None:
        problems.append("score_related is null")
    if rec["score_hard_negative"] is None:
        problems.append("score_hard_negative is null")
    if rec["score_related"] is not None and rec["score_hard_negative"] is not None:
        if rec["score_related"] <= rec["score_hard_negative"]:
            problems.append(
                f"score_related ({rec['score_related']}) <= score_hard_negative "
                f"({rec['score_hard_negative']}) -- the curated hard negative must score "
                "strictly lower than the curated true property"
            )
    return problems


def validate_and_repair_teacher_scores(
    candidates: list[dict], records: list[dict], model: str, max_repairs: int = 3
) -> list[dict]:
    """Re-issues `score_candidate` (three FRESH isolated calls -- no shared
    context across attempts, see `_call_ollama_model`'s docstring, so a
    repair is a genuine independent redraw, not a retry of the identical
    request) for any record failing `validate_teacher_record`, up to
    `max_repairs` extra attempts. Every attempt's outcome is printed. A
    candidate still failing after `max_repairs` attempts is left as-is
    with its problems recorded in `_validation_problems` -- never silently
    swapped for a fabricated value, and `build_probe_records` refuses to
    train on it (see that function's docstring)."""
    by_word = {c["word"]: c for c in candidates}
    repaired: list[dict] = []
    for rec in records:
        problems = validate_teacher_record(rec)
        attempt = 0
        while problems and attempt < max_repairs:
            attempt += 1
            print(f"  REPAIR {rec['word']!r} attempt {attempt}/{max_repairs}: {problems}")
            rec = score_candidate(by_word[rec["word"]], model)
            problems = validate_teacher_record(rec)
        rec["_validation_problems"] = problems
        if problems:
            print(f"  UNRESOLVED after {max_repairs} repairs: {rec['word']!r} -> {problems}")
        else:
            print(
                f"  OK: {rec['word']!r} score_related={rec['score_related']} "
                f"score_hard_negative={rec['score_hard_negative']}"
            )
        repaired.append(rec)
    return repaired


def run_teacher_scoring(candidates: list[dict]) -> dict:
    """Full stage-1 pipeline: resolve the teacher model, warm it up, run 3
    isolated calls per candidate, validate + self-repair (see
    `validate_and_repair_teacher_scores`), persist to
    `{RUN_NAME}.teacher_scores.json` for idempotent reuse by `train_probe`.
    If Ollama is fully unreachable, this reports the blocker honestly
    (never fabricates scores) and every candidate's score fields are
    None."""
    model, reason = resolve_teacher_model()
    print(f"teacher model resolution: model={model!r}, reason={reason!r}")

    records: list[dict] = []
    if model is None:
        for c in candidates:
            records.append(
                {
                    "word": c["word"],
                    "gloss": c["gloss"],
                    "related": c["related"],
                    "related_gloss": c["related_gloss"],
                    "hard_negative": c["hard_negative"],
                    "hard_negative_gloss": c["hard_negative_gloss"],
                    "teacher_model": None,
                    "fact_true": None,
                    "score_related": None,
                    "score_hard_negative": None,
                    "_validation_problems": ["ollama unavailable"],
                }
            )
    else:
        _warm_up_teacher_model(model)
        for c in candidates:
            rec = score_candidate(c, model)
            print(
                f"  {rec['word']!r} -> related={rec['related']!r} "
                f"fact_true={rec['fact_true']} score_related={rec['score_related']} "
                f"| hard_negative={rec['hard_negative']!r} "
                f"score_hard_negative={rec['score_hard_negative']}"
            )
            records.append(rec)
        records = validate_and_repair_teacher_scores(candidates, records, model)

    result = {
        "teacher_model_resolved": model,
        "resolution_reason": reason,
        "candidates": records,
        "ollama_blocker": None if model is not None else reason,
    }
    out_path = DATA_DIR / f"{RUN_NAME}.teacher_scores.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return result


def load_teacher_scores() -> dict:
    path = DATA_DIR / f"{RUN_NAME}.teacher_scores.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Step 2: build training records from the teacher's ACTUAL scores, extend
# the existing obj_hard_neg base training set in-memory (never disk).
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


MIN_CLEAN_CANDIDATES = 3  # below this, training on the survivors is not a meaningful probe


def build_probe_records(teacher_records: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """One MNRL triplet (anchor=word, positive=related, negative=
    hard_negative) + two graded pairs (word/related at score_related,
    word/hard_negative at score_hard_negative) per candidate -- graded
    schema matches train_graded_pairs.jsonl exactly (sentence1/sentence2/
    score/source, verified by reading the file directly). Defense-in-depth:
    re-runs `validate_teacher_record` (the same gate `run_teacher_scoring`'s
    repair loop already enforces).

    GG-approved policy (2026-07-19, after two independent GCP runs
    reproducibly found qwen3:8b cannot calibrate nariyal/samosa/dudh's
    sensory-property score even after 3 self-repair attempts each): a
    candidate that STILL fails validation after the repair loop is DROPPED
    from training, not fatal to the whole probe -- this is a genuine
    per-word teacher-calibration gap, not a stale-file/Ollama-outage
    symptom (those cases were already ruled out: two independent fresh
    `--teacher` runs reproduced the identical failure). Every dropped
    candidate is reported by name + reason in the returned `dropped` dict --
    never silently excluded. Still raises ValueError if fewer than
    MIN_CLEAN_CANDIDATES survive, since training on 0-2 words is not a
    meaningful distillation probe."""
    problems_by_word = {r["word"]: validate_teacher_record(r) for r in teacher_records}
    failing = {w: p for w, p in problems_by_word.items() if p}
    clean_records = [r for r in teacher_records if not problems_by_word[r["word"]]]
    if len(clean_records) < MIN_CLEAN_CANDIDATES:
        raise ValueError(
            f"cannot build training records -- only {len(clean_records)} of "
            f"{len(teacher_records)} candidates pass validation (need >= "
            f"{MIN_CLEAN_CANDIDATES}): {failing}"
        )
    if failing:
        print(f"DROPPED {len(failing)} candidate(s) failing teacher-score validation: {failing}")

    new_mnrl = [
        {
            "anchor": r["word"],
            "positive": r["related"],
            "negative": r["hard_negative"],
            "source": RUN_NAME,
        }
        for r in clean_records
    ]
    new_graded: list[dict] = []
    for r in clean_records:
        new_graded.append(
            {
                "sentence1": r["word"],
                "sentence2": r["related"],
                "score": r["score_related"],
                "source": RUN_NAME,
            }
        )
        new_graded.append(
            {
                "sentence1": r["word"],
                "sentence2": r["hard_negative"],
                "score": r["score_hard_negative"],
                "source": RUN_NAME,
            }
        )
    dropped = {
        "words": sorted(failing),
        "reasons": failing,
        "n_clean": len(clean_records),
        "n_total": len(teacher_records),
    }
    return new_mnrl, new_graded, dropped


def build_extended_training_set(
    teacher_records: list[dict],
) -> tuple[list[dict], list[dict], dict]:
    """The obj_hard_neg base training set (train_mnrl_pairs_hard_neg.jsonl +
    train_graded_pairs.jsonl -- the exact files the SHIPPED model trained
    on) extended in-memory with this probe's new records. Never writes to
    disk -- mirrors probe_subword_collision.py's `build_extended_training_
    set` pattern exactly."""
    base_mnrl = _load_jsonl(DATA_DIR / "train_mnrl_pairs_hard_neg.jsonl")
    base_graded = _load_jsonl(DATA_DIR / "train_graded_pairs.jsonl")
    new_mnrl, new_graded, dropped = build_probe_records(teacher_records)
    return base_mnrl + new_mnrl, base_graded + new_graded, dropped


# ---------------------------------------------------------------------------
# Step 3: train, matching the winning obj_hard_neg recipe exactly.
# ---------------------------------------------------------------------------


def train_probe(teacher_scores: dict | None = None) -> dict:
    if teacher_scores is None:
        teacher_scores = load_teacher_scores()
    teacher_records = teacher_scores["candidates"]

    extended_mnrl, extended_graded, dropped = build_extended_training_set(teacher_records)
    n_new = dropped["n_clean"]
    print(
        f"extended training set: {len(extended_mnrl)} mnrl "
        f"(base {len(extended_mnrl) - n_new} + {n_new} new), "
        f"{len(extended_graded)} graded "
        f"(base {len(extended_graded) - 2 * n_new} + {2 * n_new} new)"
    )
    if dropped["words"]:
        print(f"dropped from training (teacher-calibration failure): {dropped}")
    print(f"forced_cpu_training={FORCED_CPU_TRAINING} (gpu_free_mib={_free_mib})")

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
    elapsed = time.monotonic() - t0
    summary["_wall_clock_s"] = elapsed
    summary["_forced_cpu_training"] = FORCED_CPU_TRAINING
    summary["_dropped_candidates"] = dropped
    # BUG FIX (found by a GCP-run agent, 2026-07-19): run_training() already wrote
    # RUNS_DIR/{name}.train_summary.json to disk BEFORE these three keys were added
    # to the in-memory dict above -- evaluate_probe() reads that on-disk file, so
    # without re-writing it here, `dropped_candidates`/`trained_on` silently defaulted
    # to "nothing was dropped" downstream, mismarking dropped candidates as trained_on.
    summary_path = DATA_DIR / "runs" / f"{RUN_NAME}.train_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "dev_curve"}, indent=2))
    print(f"training wall-clock: {elapsed:.1f}s")
    return summary


# ---------------------------------------------------------------------------
# Step 4a: targeted rank check -- before (shipped) vs after (probe) full-
# vocab rank of each candidate's `related` (and, for completeness,
# `hard_negative`) word.
# ---------------------------------------------------------------------------


def _full_vocab_matrix(model_name_or_path: str) -> tuple[NDArray[np.float32], dict[str, int]]:
    """Embed the full 10495-word hi-en vocab with `model_name_or_path`, same
    tooling (vocab.load_hien_vocab + embeddings.embed_vocab) the curation
    agent used to compute commonsense_residual_candidates.json's
    `related_rank` field -- so this probe's "before" numbers are an
    independent, reproducible recomputation, not a copy-paste of the
    candidates file."""
    vocab = load_hien_vocab()
    with _model_override(model_name_or_path):
        matrix = embed_vocab(vocab, "hi-en")
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    return matrix, word_to_idx


def _rank_of(
    matrix: NDArray[np.float32], word_to_idx: dict[str, int], anchor: str, target: str
) -> int:
    """1-indexed rank of `target` among the full vocab by cosine similarity
    to `anchor`'s embedding (rank 1 = most similar)."""
    n = matrix.shape[0]
    sims = cosine_similarities(matrix, matrix[word_to_idx[anchor]])
    order = np.argsort(-sims)
    ranks = np.empty(n, dtype=np.int32)
    for rank_minus1, idx in enumerate(order):
        ranks[idx] = rank_minus1 + 1
    return int(ranks[word_to_idx[target]])


def targeted_rank_check(candidates: list[dict], before_model: str, after_model_path: str) -> dict:
    """Before (shipped) -> after (probe checkpoint) full-vocab rank
    movement for each of the 8 candidates' `related` word AND (for
    completeness/transparency, not requested by the spec but cheap and
    informative) their `hard_negative` word. Cross-checks the recomputed
    "before" rank against the candidates file's own pre-computed
    `related_rank` and reports any mismatch explicitly, rather than
    silently trusting either source."""
    before_matrix, before_idx = _full_vocab_matrix(before_model)
    after_matrix, after_idx = _full_vocab_matrix(after_model_path)

    out: dict[str, dict] = {}
    for c in candidates:
        word, related, hard_neg = c["word"], c["related"], c["hard_negative"]
        before_related_rank = _rank_of(before_matrix, before_idx, word, related)
        after_related_rank = _rank_of(after_matrix, after_idx, word, related)
        before_hardneg_rank = _rank_of(before_matrix, before_idx, word, hard_neg)
        after_hardneg_rank = _rank_of(after_matrix, after_idx, word, hard_neg)
        curated_rank = c["related_rank"]
        out[word] = {
            "related": related,
            "related_rank_before_shipped": before_related_rank,
            "related_rank_after_probe": after_related_rank,
            # positive = improved (moved to a numerically lower / better rank)
            "related_rank_improvement": before_related_rank - after_related_rank,
            "candidates_file_related_rank": curated_rank,
            "before_rank_matches_candidates_file": before_related_rank == curated_rank,
            "hard_negative": hard_neg,
            "hard_negative_rank_before_shipped": before_hardneg_rank,
            "hard_negative_rank_after_probe": after_hardneg_rank,
            "vocab_size": int(before_matrix.shape[0]),
        }
    return out


# ---------------------------------------------------------------------------
# Step 4b/4c: full-34-secret regression floor + overfitting caveat.
# ---------------------------------------------------------------------------

OVERFITTING_CAVEAT = (
    "This probe trains DIRECTLY on the CLEAN subset of the 8 target words' own "
    "(anchor, related, hard_negative) triplets/graded pairs -- a large rank improvement "
    "on trained words is EXPECTED from direct training-set exposure and is NOT strong "
    "evidence the distillation APPROACH generalizes to held-out commonsense words never "
    "seen in training. Generalization to unseen commonsense pairs is tested separately by "
    "lever L6 (a different, held-out-word probe) -- not duplicated or claimed here. "
    "Separately: candidates in `dropped_candidates` were EXCLUDED from training entirely "
    "(reproducible teacher-model calibration failure on qwen3:8b across two independent "
    "runs, GG-approved policy 2026-07-19) -- their rank movement in "
    "`targeted_word_rank_movement` (marked trained_on=false) should be near-zero/noise, "
    "since they were never trained on; a large movement there would indicate an "
    "unexpected leak or bug, not a real distillation effect."
)


def evaluate_probe(model_path: str | None = None, teacher_scores: dict | None = None) -> dict:
    summary_path = DATA_DIR / "runs" / f"{RUN_NAME}.train_summary.json"
    train_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if model_path is None:
        model_path = train_summary["output_dir"]
    if teacher_scores is None:
        teacher_scores = load_teacher_scores()
    dropped_candidates = train_summary.get(
        "_dropped_candidates", {"words": [], "reasons": {}, "n_clean": None, "n_total": None}
    )

    candidates = load_candidates()

    probe_dim1 = _public_benchmark_dim1_records(model_path)
    probe_dim2 = _public_benchmark_dim2_result(model_path)
    shipped_dim1 = _shipped_model_dim1_records_34()
    shipped_dim2 = _shipped_model_dim2_records_34()

    probe_dim1_ci = bootstrap_dim1_spearman_ci(probe_dim1)
    probe_dim2_ci = bootstrap_dim2_pass_rate_ci(probe_dim2["records"])
    shipped_dim1_ci = bootstrap_dim1_spearman_ci(shipped_dim1)
    shipped_dim2_ci = bootstrap_dim2_pass_rate_ci(shipped_dim2)

    dim1_delta = paired_bootstrap_dim1_delta(shipped_dim1, probe_dim1)
    dim2_delta = paired_bootstrap_dim2_delta(shipped_dim2, probe_dim2["records"])

    dim1_floor = dim1_regression_floor(shipped_dim1, probe_dim1)
    dim2_floor = dim2_regression_floor(shipped_dim2, probe_dim2["records"])

    targeted = targeted_rank_check(candidates, SHIPPED_MODEL, model_path)
    for word, row in targeted.items():
        row["trained_on"] = word not in dropped_candidates["words"]

    result = {
        "run_name": RUN_NAME,
        "shipped_model": SHIPPED_MODEL,
        "probe_model_path": model_path,
        "forced_cpu_training": FORCED_CPU_TRAINING,
        "dropped_candidates": dropped_candidates,
        "teacher_scores": teacher_scores,
        "n_dim1_secrets": len({r["secret"] for r in probe_dim1}),
        "n_dim1_scenarios": len(probe_dim1),
        "n_dim2_pairs": len(probe_dim2["records"]),
        "probe_dim1_spearman_ci": probe_dim1_ci,
        "probe_dim2_pass_rate_ci": probe_dim2_ci,
        "shipped_dim1_spearman_ci": shipped_dim1_ci,
        "shipped_dim2_pass_rate_ci": shipped_dim2_ci,
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim1_regression_floor_all_34": dim1_floor,
        "dim2_regression_floor_all_34": dim2_floor,
        "targeted_word_rank_movement": targeted,
        "overfitting_caveat": OVERFITTING_CAVEAT,
    }
    out_path = DATA_DIR / f"{RUN_NAME}.eval_result.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="no-leakage check only")
    parser.add_argument("--teacher", action="store_true", help="run teacher scoring")
    parser.add_argument("--train", action="store_true", help="run the probe fine-tune")
    parser.add_argument("--eval", action="store_true", help="evaluate the trained probe checkpoint")
    parser.add_argument(
        "--reuse-teacher-cache",
        action="store_true",
        help=(
            "reuse an existing teacher_scores.json instead of regenerating (default is to "
            "always regenerate fresh -- avoids a stale/partially-repaired cache silently "
            "feeding --train, and avoids a cross-process race with a separate --teacher run)"
        ),
    )
    args = parser.parse_args()

    candidates = load_candidates()

    if args.check_only or not (args.teacher or args.train or args.eval):
        print(json.dumps(verify_no_leakage(candidates), indent=2))
        if not (args.teacher or args.train or args.eval):
            return

    teacher_scores: dict | None = None
    if args.teacher or args.train:
        verify_no_leakage(candidates)
        teacher_path = DATA_DIR / f"{RUN_NAME}.teacher_scores.json"
        if args.reuse_teacher_cache and teacher_path.exists():
            teacher_scores = load_teacher_scores()
        else:
            teacher_scores = run_teacher_scoring(candidates)

    if args.train:
        train_probe(teacher_scores)
    if args.eval:
        evaluate_probe(teacher_scores=teacher_scores)


if __name__ == "__main__":
    main()
