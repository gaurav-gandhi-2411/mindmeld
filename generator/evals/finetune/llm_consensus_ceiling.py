from __future__ import annotations

"""
spec-metrics-ceiling-calibration.md WORKSTREAM 2 -- LLM-consensus label
ceiling. Replaces the never-annotated manual-labeling task
(prepare_label_ceiling_sample.py / score_label_ceiling.py's original human
path -- GG's standing policy is "NEVER manual-label, use multi-LLM
consensus": see spec-metrics-ceiling-calibration.md's "Standing policies").

Two local, $0, different-family judges -- qwen3:8b (Alibaba/Qwen family) and
llama3.1:8b (Meta/Llama family) -- rate the same stratified 75-item sample
prepare_label_ceiling_sample.py already draws from the frozen 34-secret
PUBLIC benchmark (evals/finetune/data/public_benchmark_staging/dim1_hien.json),
BLIND (never shown the benchmark's own tier) and with per-item presentation-
order randomised. Each judge is self-consistency-sampled k>=3 times at
temperature>0 before a per-judge majority vote; the two judges' majority
votes are then compared (Cohen's weighted kappa, reusing
score_label_ceiling.py's existing implementation) to measure whether the
consensus is trustworthy at all. A MANDATORY calibration gate (unambiguous
synonym/random-filler control items) runs first and can hard-block the
whole run if either judge fails it -- see run_calibration_gate().

Reused, not reimplemented:
  - prepare_label_ceiling_sample.stratified_sample() / secret_to_domain() --
    same tier x domain stratified draw used for the (never-annotated)
    manual path, seed=42, so this ceiling is measured on the exact same
    75-item population that would have gone to GG.
  - score_label_ceiling.cohens_kappa / weighted_kappa_from_confusion /
    bootstrap_kappa_ci / confusion_matrix / raw_agreement_rate -- the
    inter-judge kappa trust gate is the SAME linear-weighted-kappa machinery
    already built and unit-tested for the (originally human-vs-AI) label-
    ceiling comparison; here it scores judge-A-vs-judge-B instead of
    GG-vs-AI, same 3-level near/mid/far ordinal scale, same math.
  - The dual-family Ollama wire pattern (http://localhost:11434/api/generate,
    format=<json-schema>, think=False for qwen3) follows
    probe_lever_l2_devanagari_hybrid.py / probe_lever_l4_distillation.py's
    established precedent exactly, rather than inventing a new HTTP client.

Protocol steps implemented (spec numbering):
  1. Two different-family judges: qwen3:8b, llama3.1:8b. Verified live
     against /api/tags before anything runs -- never assumed pulled.
  2. Blind + order-randomised: judges are given ONLY (secret, gloss, word) --
     never the benchmark tier, never the other judge's output. Which of
     secret/word is presented as "Word A" vs "Word B" is a seeded coin flip
     PER ITEM (hash of secret+word+seed, stable regardless of processing
     order), and the SEQUENCE of items sent to each judge is itself a
     seeded shuffle (see _shuffle_items). Reproducible given seed=42.
  3. Self-consistency: k=3 independent temperature=0.7 samples per
     (judge, item), per-judge majority vote before any cross-judge
     comparison (majority_vote(), ties broken toward "mid" -- the neutral/
     uncertain outcome, not an arbitrary extreme). Note: the SAMPLES
     themselves are not bit-reproducible (temperature>0 local sampling has
     no practical determinism guarantee across Ollama versions/builds) --
     what IS seeded and reproducible is which item goes to which judge in
     which order and with which presentation order; per this task's own
     scope, only the deterministic parts (order randomisation, calibration
     gate arithmetic, sensitivity-analysis arithmetic) are unit-tested.
  4. Mandatory judge-calibration gate, run FIRST: unambiguous "translation"-
     subtype near-tier exact-synonym pairs (must resolve near) and
     deterministic domain-disjoint "hash-random" filler pairs (must resolve
     far) --
     see build_control_near()/build_control_far(). Bar: 90% control
     accuracy per judge (see run_calibration_gate() docstring for the
     justification). A judge below the bar is a HARD BLOCKER -- there is no
     third local model family available to substitute, so this run reports
     the blocker and stops rather than silently downgrading to a single
     judge (that would defeat the entire point of the protocol).
  5. Cohen's (linear-weighted) kappa between the two judges' majority votes
     on the main 75-item sample -- the trust gate. Landis-Koch banded:
     kappa < 0.4 (poor/fair) => ceiling reported UNRELIABLE, not quietly
     used.
  6. Disagreement handling: only two model families are available in this
     environment (no third), so per the spec's own documented fallback,
     judge disagreements are marked CONTESTED, not adjudicated by a third
     judge, and the contested count/rate is itself reported as a finding.
  7. Ceiling = agreement rate between the (post-self-consistency,
     post-disagreement-handling) consensus label and the benchmark's own
     existing tier, on the resolved (non-contested) subset -- the primary
     point estimate.
  8. Sensitivity analysis: the ceiling recomputed under contested-as-agree
     (optimistic) and contested-as-disagree (conservative) tie-break rules,
     third-judge explicitly marked N/A (see step 6) -- reports the range,
     not one cherry-picked number.
  9. Current shipped-model performance (dim1 Spearman AND band-tier
     accuracy, both pulled from evals/finetune/data/current_state_report.json
     -- never recomputed/estimated) re-expressed as % of the ceiling, with
     the division shown explicitly in the rendered report.
  10. Everywhere reported: labelled LLM-CONSENSUS ceiling, not human ground
      truth, with the correlated-blind-spots caveat stated verbatim (see
      LLM_CONSENSUS_CAVEAT below -- drop-in ready for a model/benchmark
      card).

Run (from generator/):
    uv run python -m evals.finetune.llm_consensus_ceiling
    uv run python -m evals.finetune.llm_consensus_ceiling \\
        --main-sample-size 10 --control-size 4 --k 2
        (fast smoke run against REAL Ollama calls -- NOT the reported numbers)
"""

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from evals.finetune.prepare_label_ceiling_sample import (
    PER_TIER_TARGET,
    secret_to_domain,
    stratified_sample,
)
from evals.finetune.score_label_ceiling import (
    STAGING_DIM1_HIEN,
    bootstrap_kappa_ci,
    confusion_matrix,
    raw_agreement_rate,
)
from evals.gen_dim1_benchmark_supplement import BENCHMARK_SUPPLEMENT_PAIRS

FINETUNE_DIR = Path(__file__).parent
DATA_DIR = FINETUNE_DIR / "data"
CURRENT_STATE_REPORT = DATA_DIR / "current_state_report.json"
OUT_JSON = DATA_DIR / "llm_consensus_ceiling_report.json"
OUT_MD = DATA_DIR / "llm_consensus_ceiling_report.md"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
JUDGE_MODELS: tuple[str, ...] = ("qwen3:8b", "llama3.1:8b")  # two DIFFERENT model families
TIMEOUT_SECONDS = 300  # generous -- first call per model pays a cold-load penalty (~10s
# observed at probe time), subsequent warm calls are ~2-3s; see module docstring.

SEED = 42
CATEGORIES: tuple[str, ...] = ("near", "mid", "far")
TEMPERATURE = 0.7  # documented choice: high enough that k=3 self-consistency samples can
# genuinely disagree (temperature=0 would make k>1 pointless -- every sample identical),
# low enough that the model still reliably returns one of the three schema-constrained
# labels rather than degenerating into off-distribution text (consistent with this repo's
# other Ollama judge callers' choice of a moderate, non-zero temperature for graded/sampled
# judgments -- e.g. probe_lever_l4_distillation.py uses 0.2 for a stricter single-shot
# grading task; this is a self-consistency VOTING task, which specifically wants sample
# diversity, hence higher).
K_SELF_CONSISTENCY = 3  # spec floor ("k>=3")
CALIBRATION_BAR = 0.90  # justification: control items are constructed to be UNAMBIGUOUS
# (exact-synonym-class pairs that must be near, domain-disjoint hash-random fillers that
# must be far) -- a competent 8B instruction-tuned judge should get these right essentially
# every time. 90% (not 100%) tolerates a small amount of genuine local-model noise (a single
# miss in a 15-item category) without moving the bar so low that a judge with a real,
# systematic blind spot could still pass. Below 90%, that judge's real-sample votes cannot
# be trusted more than the noise floor itself, so it is a hard blocker, not a soft warning.
CONTROL_NEAR_SIZE = 15
CONTROL_FAR_SIZE = 15
MAIN_SAMPLE_SIZE = 75  # matches prepare_label_ceiling_sample.py's TARGET_TOTAL exactly --
# same population the (never-annotated) manual GG path would have judged.

LLM_CONSENSUS_CAVEAT = (
    "This is an LLM-CONSENSUS ceiling, NOT a human-annotated ceiling. It was produced by "
    "two local LLM judges from different model families (qwen3:8b, llama3.1:8b), blind to "
    "the benchmark's own labels, self-consistency-sampled and cross-checked for inter-judge "
    "agreement -- it was never reviewed by a human annotator. KNOWN LIMITATION: both judges "
    "are LLMs and may share correlated blind spots inherited from broadly similar "
    "training-data distributions (e.g. the same underrepresented Hinglish "
    "romanization/register patterns, or the same class of associative-commonsense gaps) -- "
    "agreement between them is evidence of consistency, not proof of correctness against an "
    "independent ground truth."
)

_TIER_SCHEMA = {
    "type": "object",
    "properties": {"tier": {"type": "string", "enum": list(CATEGORIES)}},
    "required": ["tier"],
}

_TIER_PROMPT = """You are judging word relatedness for a Hinglish (Hindi-English) \
word-association game.

{a_label}: {a_desc}
{b_label}: {b_desc}

How closely related are these two words in meaning? Judge ONLY semantic/associative \
relatedness, not spelling similarity. Choose exactly one:
  near -- directly or strongly related (synonyms, close associates, direct translations)
  mid  -- moderately or loosely related (same general topic/domain, but not a direct match)
  far  -- not really related at all

Respond with ONLY: {{"tier": "near"|"mid"|"far"}}"""


class ConsensusJudgeUnavailableError(RuntimeError):
    """Raised when neither judge model is reachable at all (server down)."""


# ---------------------------------------------------------------------------
# Ollama liveness / model availability -- never assumed.
# ---------------------------------------------------------------------------


def check_ollama_up() -> bool:
    """True iff a local Ollama server answers /api/tags."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def list_available_models() -> set[str]:
    """Set of model names/tags currently pulled, per /api/tags. Empty set if
    the server is unreachable (caller decides how to react)."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:  # noqa: S310
            payload = json.loads(resp.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
        return set()
    return {m.get("name", "") for m in payload.get("models", [])}


def verify_judges_available() -> dict[str, bool]:
    """{model: is_pulled} for every model in JUDGE_MODELS. Raises
    ConsensusJudgeUnavailableError if Ollama itself is unreachable (a
    distinct failure mode from "model not pulled")."""
    if not check_ollama_up():
        raise ConsensusJudgeUnavailableError(
            f"Ollama server not reachable at {OLLAMA_TAGS_URL}. Run `ollama serve` first."
        )
    available = list_available_models()
    return {m: m in available for m in JUDGE_MODELS}


# ---------------------------------------------------------------------------
# Blind, order-randomised prompt construction.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeItem:
    """One (secret, word) pair to be judged -- either a control item (with a
    known `expected_tier`) or a real sample item (with the withheld
    `benchmark_tier`). `domain` is carried through for reporting only."""

    secret: str
    gloss: str
    word: str
    domain: str
    label: str  # "near" | "far" (control expected) | the withheld benchmark tier


def _secret_first(secret: str, word: str, seed: int) -> bool:
    """Seeded per-item coin flip for which of (secret, word) is presented as
    "Word A" -- stable given (secret, word, seed) regardless of what order
    items are iterated in, so item-order shuffling (see _shuffle_items)
    never perturbs this independent decision."""
    key = f"{seed}|{secret}|{word}".encode()
    digest = hashlib.sha256(key).hexdigest()
    return int(digest[:8], 16) % 2 == 0


def build_prompt(item: JudgeItem, seed: int) -> str:
    """Blind, order-randomised judge prompt for one item. Never includes
    `item.label` (the withheld tier) anywhere."""
    secret_desc = f'"{item.secret}" (meaning: {item.gloss})'
    word_desc = f'"{item.word}"'
    if _secret_first(item.secret, item.word, seed):
        a_desc, b_desc = secret_desc, word_desc
    else:
        a_desc, b_desc = word_desc, secret_desc
    return _TIER_PROMPT.format(a_label="Word A", a_desc=a_desc, b_label="Word B", b_desc=b_desc)


def _shuffle_items(items: list[JudgeItem], seed: int) -> list[JudgeItem]:
    """Seeded shuffle of presentation ORDER (spec step 2's "randomise item
    order") -- a separate concern from per-item Word-A/Word-B order."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(items))
    return [items[i] for i in idx]


# ---------------------------------------------------------------------------
# Ollama call + self-consistency majority vote.
# ---------------------------------------------------------------------------


def call_ollama_tier(model: str, prompt: str, temperature: float = TEMPERATURE) -> str | None:
    """One sampled call to `model`. Returns the parsed tier string, or None
    on ANY failure (unreachable, timeout, malformed JSON, tier not in
    CATEGORIES) -- never raises, never fabricates a label; callers count
    None outcomes and report them, they do not silently drop them."""
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,  # no-op for non-thinking models (llama3.1), silences qwen3's
            # reasoning trace so `response` is the bare JSON object, not a <think>...</think>
            # prefix -- same flag judge_client.py's qwen3 caller uses.
            "format": _TIER_SCHEMA,
            "options": {"temperature": temperature},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            outer = json.loads(response.read())
        parsed = json.loads(outer.get("response", ""))
        tier = str(parsed.get("tier", "")).strip().lower()
    except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError, KeyError):
        return None
    return tier if tier in CATEGORIES else None


def majority_vote(votes: list[str | None]) -> str | None:
    """Majority label across a list of (possibly-None) votes. None entries
    are dropped before voting; if ALL entries are None, returns None (the
    caller treats this as "judge unavailable for this item", not a
    disagreement). On a genuine tie (including a bare near/far split with
    zero mid votes), the tie-break is always toward "mid" -- the neutral,
    least-committal outcome -- rather than an arbitrary alphabetical
    extreme, since a tie is itself evidence of within-judge uncertainty."""
    valid = [v for v in votes if v in CATEGORIES]
    if not valid:
        return None
    counts = Counter(valid)
    top = max(counts.values())
    tied = sorted(c for c, n in counts.items() if n == top)
    if len(tied) == 1:
        return tied[0]
    return "mid"  # any tie (including a bare near/far split) resolves to the neutral outcome


def self_consistency_vote(
    model: str,
    item: JudgeItem,
    seed: int,
    k: int = K_SELF_CONSISTENCY,
    temperature: float = TEMPERATURE,
) -> dict:
    """k independent sampled calls to `model` for `item`, majority-voted.
    Returns {"majority": str|None, "votes": list[str|None], "n_failed": int}
    -- raw votes are always kept so a report can show self-consistency
    dispersion, not just the collapsed majority."""
    prompt = build_prompt(item, seed)
    votes = [call_ollama_tier(model, prompt, temperature) for _ in range(k)]
    return {
        "majority": majority_vote(votes),
        "votes": votes,
        "n_failed": sum(1 for v in votes if v is None),
    }


# ---------------------------------------------------------------------------
# Control-item construction (spec step 4).
# ---------------------------------------------------------------------------


def _load_translation_near_pairs() -> list[tuple[str, str, str, str]]:
    """(secret, gloss, word, domain) for every subtype="translation"
    near-tier record in the frozen public benchmark -- these are literal
    exact-synonym pairs (`word` IS the secret's own canonical English
    translation), matching the spec's explicit control-set language
    ("exact-synonym pairs that must resolve to near") as closely as
    possible. DEVIATION from an earlier draft of this module, which used
    subtype="associate" records instead (a looser "strongly related, not
    necessarily exact" class) -- an early smoke run against real Ollama
    calls (see task notes) surfaced a genuine borderline case in that class
    ("besan"/wheat -- besan is CHICKPEA flour, not wheat flour; related by
    domain but not a true synonym) that both judges scored inconsistently,
    which is exactly the kind of avoidable ambiguity a CALIBRATION control
    item must not have. Being "trivial" is the intended property of a
    control item, not a flaw."""
    records = json.loads(STAGING_DIM1_HIEN.read_text(encoding="utf-8"))
    gloss_of = {hien: en for hien, en, _domain in BENCHMARK_SUPPLEMENT_PAIRS}
    domain_of = secret_to_domain()
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str, str]] = []
    for r in sorted(records, key=lambda r: (r["secret"], r["word"])):
        if r.get("subtype") != "translation" or r["tier"] != "near":
            continue
        key = (r["secret"], r["word"])
        if key in seen:
            continue
        seen.add(key)
        out.append((r["secret"], gloss_of[r["secret"]], r["word"], domain_of[r["secret"]]))
    return out


def build_control_near(
    n: int = CONTROL_NEAR_SIZE, exclude: frozenset[tuple[str, str]] = frozenset()
) -> list[JudgeItem]:
    """n unambiguous "must resolve near" control items, drawn from the
    benchmark's own translation-subtype near-tier records (real,
    previously human-curated exact Hindi->English translation pairs -- see
    _load_translation_near_pairs' docstring for why translation, not
    associate, subtype was chosen), excluding any (secret, word) pair
    already drawn into the main ceiling sample so the calibration gate
    stays methodologically independent of the sample it gates."""
    candidates = [
        (s, g, w, d) for s, g, w, d in _load_translation_near_pairs() if (s, w) not in exclude
    ]
    chosen = candidates[:n]
    return [
        JudgeItem(secret=s, gloss=g, word=w, domain=d, label="near") for s, g, w, d in chosen
    ]


def build_control_far(
    n: int = CONTROL_FAR_SIZE,
    seed: int = SEED + 5000,  # derived seed, documented: offset from the base seed so this
    # deterministic construction never collides with any other seeded draw in this module.
    exclude: frozenset[tuple[str, str]] = frozenset(),
) -> list[JudgeItem]:
    """n unambiguous "must resolve far" control items -- deterministic
    "hash-random" domain-disjoint pairing: every one of the benchmark's 34
    secrets is paired with ANOTHER secret's English gloss word via a seeded
    permutation, keeping only pairs whose secrets/glosses come from
    DIFFERENT domains (nature/emotion/abstract/object/place/food/kinship)
    and whose word is not the secret's own gloss (would be a translation,
    i.e. "near", not "far") -- domain-disjointness is a structural proxy
    for unrelatedness, spot-checked by hand during development (e.g.
    "sharm"/shyness vs "border", "dehat"/countryside vs "yogurt" -- see
    task notes) rather than assumed blindly."""
    domain_of = {h: d for h, _e, d in BENCHMARK_SUPPLEMENT_PAIRS}
    gloss_of = {h: e for h, e, _d in BENCHMARK_SUPPLEMENT_PAIRS}
    word_domain_of = {e: d for _h, e, d in BENCHMARK_SUPPLEMENT_PAIRS}
    secrets = sorted(domain_of)
    fillers = sorted(word_domain_of)

    rng = np.random.default_rng(seed)
    perm_secrets = [str(x) for x in rng.permutation(secrets)]
    perm_fillers = [str(x) for x in rng.permutation(fillers)]

    out: list[JudgeItem] = []
    for s, f in zip(perm_secrets, perm_fillers, strict=True):
        if domain_of[s] == word_domain_of[f]:
            continue
        if f == gloss_of[s]:
            continue
        if (s, f) in exclude:
            continue
        out.append(JudgeItem(secret=s, gloss=gloss_of[s], word=f, domain=domain_of[s], label="far"))
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------------------
# Main sample (reused stratified draw).
# ---------------------------------------------------------------------------


def build_main_sample(
    per_tier_target: int = PER_TIER_TARGET, seed: int = SEED
) -> list[JudgeItem]:
    """The SAME tier x domain stratified 75-item draw
    prepare_label_ceiling_sample.py builds for the (never-annotated) manual
    path -- reused verbatim, not reimplemented, so this ceiling is measured
    on the exact population the spec's original protocol targeted."""
    domain_of = secret_to_domain()
    gloss_of = {h: e for h, e, _d in BENCHMARK_SUPPLEMENT_PAIRS}
    records = json.loads(STAGING_DIM1_HIEN.read_text(encoding="utf-8"))
    for r in records:
        r["domain"] = domain_of[r["secret"]]
    sample = stratified_sample(records, domain_of, per_tier_target=per_tier_target, seed=seed)
    return [
        JudgeItem(
            secret=r["secret"],
            gloss=gloss_of[r["secret"]],
            word=r["word"],
            domain=r["domain"],
            label=r["tier"],
        )
        for r in sample
    ]


# ---------------------------------------------------------------------------
# Calibration gate (spec step 4) -- run FIRST.
# ---------------------------------------------------------------------------


def run_calibration_gate(
    control_items: list[JudgeItem],
    models: tuple[str, ...] = JUDGE_MODELS,
    seed: int = SEED,
    k: int = K_SELF_CONSISTENCY,
    verbose: bool = True,
) -> dict:
    """Runs every control item through every judge (self-consistency
    majority-voted) and reports per-judge accuracy against each item's
    known `label`. Returns {"per_judge": {model: {...}}, "raw": [...]}.
    `verbose` prints flushed per-item progress -- this phase makes real,
    potentially slow (multi-second per call) Ollama HTTP calls, and this
    module's own main() only prints once at the very end otherwise, which
    makes a long background run look silently hung; incremental progress
    output is a debuggability requirement, not cosmetic."""
    ordered = _shuffle_items(control_items, seed=seed + 2)
    raw: list[dict] = []
    per_judge_correct: dict[str, int] = {m: 0 for m in models}
    per_judge_near_correct: dict[str, int] = {m: 0 for m in models}
    per_judge_near_total: dict[str, int] = {m: 0 for m in models}
    per_judge_far_correct: dict[str, int] = {m: 0 for m in models}
    per_judge_far_total: dict[str, int] = {m: 0 for m in models}

    for model in models:  # loop per-model OUTER, per-item INNER -- minimises Ollama's
        # model-swap latency (each swap costs a multi-second reload; see module docstring)
        for i, item in enumerate(ordered, start=1):
            t_item = time.time()
            result = self_consistency_vote(model, item, seed=seed, k=k)
            if verbose:
                print(
                    f"[calibration] {model} {i}/{len(ordered)} {item.secret}/{item.word} "
                    f"-> {result['majority']} ({time.time() - t_item:.1f}s)",
                    flush=True,
                )
            correct = result["majority"] == item.label
            per_judge_correct[model] += int(correct)
            if item.label == "near":
                per_judge_near_total[model] += 1
                per_judge_near_correct[model] += int(correct)
            else:
                per_judge_far_total[model] += 1
                per_judge_far_correct[model] += int(correct)
            raw.append(
                {
                    "model": model,
                    "secret": item.secret,
                    "word": item.word,
                    "expected": item.label,
                    "majority": result["majority"],
                    "votes": result["votes"],
                    "correct": correct,
                }
            )

    n = len(ordered)
    per_judge = {}
    for m in models:
        accuracy = per_judge_correct[m] / n if n else None
        near_acc = (
            per_judge_near_correct[m] / per_judge_near_total[m]
            if per_judge_near_total[m]
            else None
        )
        far_acc = (
            per_judge_far_correct[m] / per_judge_far_total[m] if per_judge_far_total[m] else None
        )
        per_judge[m] = {
            "accuracy": accuracy,
            "near_accuracy": near_acc,
            "far_accuracy": far_acc,
            "n_control_items": n,
            "n_correct": per_judge_correct[m],
            "bar": CALIBRATION_BAR,
            "passed": accuracy is not None and accuracy >= CALIBRATION_BAR,
        }
    return {"per_judge": per_judge, "raw": raw}


def calibration_verdict(gate_result: dict) -> tuple[bool, str]:
    """(all_passed, message) -- the hard-blocker decision point."""
    per_judge = gate_result["per_judge"]
    failed = [m for m, r in per_judge.items() if not r["passed"]]
    if not failed:
        return True, "All judges passed the calibration gate."
    detail = ", ".join(f"{m} ({per_judge[m]['accuracy']:.1%})" for m in failed)
    return False, (
        f"HARD BLOCKER: judge(s) failed the {CALIBRATION_BAR:.0%} calibration bar: {detail}. "
        "No third local model family is available in this environment to substitute -- per "
        "spec step 4, a judge that fails calibration must be excluded, not used, and with "
        "only two judges available this means the LLM-consensus protocol cannot proceed."
    )


# ---------------------------------------------------------------------------
# Main-sample judging + inter-judge kappa (spec steps 5-6).
# ---------------------------------------------------------------------------


def run_main_sample(
    items: list[JudgeItem],
    models: tuple[str, ...] = JUDGE_MODELS,
    seed: int = SEED,
    k: int = K_SELF_CONSISTENCY,
    verbose: bool = True,
) -> dict:
    """Runs every main-sample item through every judge. Returns
    {"per_item": [...], "raw": {model: [...]}}. `verbose`: see
    run_calibration_gate's docstring -- same incremental-progress rationale."""
    ordered = _shuffle_items(items, seed=seed + 1)
    raw: dict[str, list[dict]] = {m: [] for m in models}
    for model in models:
        for i, item in enumerate(ordered, start=1):
            t_item = time.time()
            result = self_consistency_vote(model, item, seed=seed, k=k)
            if verbose:
                print(
                    f"[main-sample] {model} {i}/{len(ordered)} {item.secret}/{item.word} "
                    f"-> {result['majority']} ({time.time() - t_item:.1f}s)",
                    flush=True,
                )
            raw[model].append(
                {
                    "secret": item.secret,
                    "word": item.word,
                    "domain": item.domain,
                    "benchmark_tier": item.label,
                    "majority": result["majority"],
                    "votes": result["votes"],
                }
            )
    # index by (secret, word) so per-item cross-judge comparison is order-independent
    by_key: dict[str, dict[tuple[str, str], dict]] = {
        m: {(r["secret"], r["word"]): r for r in raw[m]} for m in models
    }
    per_item = []
    for item in ordered:
        key = (item.secret, item.word)
        judge_a, judge_b = models[0], models[1]
        label_a = by_key[judge_a][key]["majority"]
        label_b = by_key[judge_b][key]["majority"]
        if label_a is None or label_b is None:
            status = "JUDGE_UNAVAILABLE"
            consensus = None
        elif label_a == label_b:
            status = "AGREE"
            consensus = label_a
        else:
            status = "CONTESTED"
            consensus = None
        per_item.append(
            {
                "secret": item.secret,
                "word": item.word,
                "domain": item.domain,
                "benchmark_tier": item.label,
                judge_a: label_a,
                judge_b: label_b,
                "status": status,
                "consensus": consensus,
            }
        )
    return {"per_item": per_item, "raw": raw}


def compute_inter_judge_kappa(per_item: list[dict], models: tuple[str, ...] = JUDGE_MODELS) -> dict:
    """Cohen's linear-weighted kappa between the two judges' majority
    votes, via score_label_ceiling.py's existing bootstrap_kappa_ci (reused
    verbatim -- same math as the human<->AI comparison it was built for).
    Landis-Koch banded reliability verdict."""
    judge_a, judge_b = models
    pairs = [
        (r[judge_a], r[judge_b])
        for r in per_item
        if r[judge_a] is not None and r[judge_b] is not None
    ]
    kappa_ci = bootstrap_kappa_ci(pairs, categories=CATEGORIES, weights="linear")
    raw_agree = raw_agreement_rate(pairs)
    kappa = kappa_ci["point"]
    if kappa is None or np.isnan(kappa):
        band = "undetermined"
        reliable = False
    elif kappa < 0.0:
        band = "poor"
        reliable = False
    elif kappa < 0.20:
        band = "slight"
        reliable = False
    elif kappa < 0.40:
        band = "fair"
        reliable = False
    elif kappa < 0.60:
        band = "moderate"
        reliable = True
    elif kappa < 0.80:
        band = "substantial"
        reliable = True
    else:
        band = "almost perfect"
        reliable = True
    return {
        "kappa": kappa_ci,
        "landis_koch_band": band,
        "reliable": reliable,  # spec step 5's trust gate: kappa < 0.4 (poor/fair) => UNRELIABLE
        "raw_agreement_rate": raw_agree,
        "n_pairs": len(pairs),
        "confusion_matrix": {
            "categories": list(CATEGORIES),
            "rows_are": judge_a,
            "cols_are": judge_b,
            "matrix": confusion_matrix(pairs, CATEGORIES).tolist(),
        },
    }


# ---------------------------------------------------------------------------
# Ceiling + sensitivity analysis (spec steps 7-8).
# ---------------------------------------------------------------------------


def compute_ceiling(per_item: list[dict]) -> dict:
    """Agreement rate between consensus label and benchmark tier, under
    three tie-break rules for CONTESTED items (spec step 8's sensitivity
    analysis) -- third-judge explicitly N/A (spec step 6: only two model
    families available in this environment)."""
    resolved = [r for r in per_item if r["status"] == "AGREE"]
    contested = [r for r in per_item if r["status"] == "CONTESTED"]
    unavailable = [r for r in per_item if r["status"] == "JUDGE_UNAVAILABLE"]
    n_total = len(resolved) + len(contested)  # unavailable items excluded from every
    # ceiling denominator -- they carry no consensus signal either way, so including them
    # would silently bias every sensitivity rule toward whichever tie-break the caller picks.

    matches_resolved = sum(1 for r in resolved if r["consensus"] == r["benchmark_tier"])

    ceiling_resolved_only = matches_resolved / len(resolved) if resolved else None
    ceiling_contested_as_agree = (
        (matches_resolved + len(contested)) / n_total if n_total else None
    )
    ceiling_contested_as_disagree = matches_resolved / n_total if n_total else None

    return {
        "n_total_scored": n_total,
        "n_resolved": len(resolved),
        "n_contested": len(contested),
        "n_judge_unavailable": len(unavailable),
        "contested_rate": len(contested) / n_total if n_total else None,
        "sensitivity": {
            "resolved_only": {
                "value": ceiling_resolved_only,
                "arithmetic": f"{matches_resolved}/{len(resolved)}" if resolved else "n/a",
                "description": (
                    "PRIMARY point estimate -- agreement rate over the resolved "
                    "(non-contested) subset only, contested items dropped from both "
                    "numerator and denominator."
                ),
            },
            "contested_as_agree": {
                "value": ceiling_contested_as_agree,
                "arithmetic": f"({matches_resolved}+{len(contested)})/{n_total}"
                if n_total
                else "n/a",
                "description": (
                    "OPTIMISTIC upper bound -- assumes every contested item WOULD have "
                    "agreed with the benchmark tier had it been resolved."
                ),
            },
            "contested_as_disagree": {
                "value": ceiling_contested_as_disagree,
                "arithmetic": f"{matches_resolved}/{n_total}" if n_total else "n/a",
                "description": (
                    "CONSERVATIVE lower bound -- assumes every contested item would have "
                    "disagreed with the benchmark tier."
                ),
            },
            "third_judge": {
                "value": None,
                "description": (
                    "N/A -- only two local model families (qwen3, llama3.1) are available "
                    "in this environment; per spec step 6's documented fallback, "
                    "disagreements are marked CONTESTED rather than adjudicated by a third "
                    "judge."
                ),
            },
        },
        "contested_examples": [
            {
                "secret": r["secret"],
                "word": r["word"],
                "benchmark_tier": r["benchmark_tier"],
                **{m: r[m] for m in JUDGE_MODELS},
            }
            for r in contested[:10]
        ],
    }


# ---------------------------------------------------------------------------
# Current performance as % of ceiling (spec step 9).
# ---------------------------------------------------------------------------


def load_current_state_metrics(path: Path = CURRENT_STATE_REPORT) -> dict:
    """dim1 Spearman + band-tier accuracy, READ AS-IS from the existing
    current_state_report.json checkpoint -- never recomputed here (this
    module measures the BENCHMARK's ceiling, not the model)."""
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        "dim1_spearman": report["shipped_dim1_spearman_ci"]["point"],
        "band_accuracy_overall": report["band_calibration"]["current_formula"]["band_accuracy"][
            "overall"
        ],
    }


def performance_as_pct_of_ceiling(current: dict, ceiling_point: float | None) -> dict:
    """Both current-performance metrics, each divided by the primary
    (resolved-only) ceiling estimate, arithmetic shown explicitly."""
    if not ceiling_point:
        return {
            "ceiling_point_used": ceiling_point,
            "dim1_spearman_pct_of_ceiling": None,
            "band_accuracy_pct_of_ceiling": None,
            "note": "Ceiling point estimate is None/zero -- cannot compute a percentage.",
        }
    dim1 = current["dim1_spearman"]
    band = current["band_accuracy_overall"]
    return {
        "ceiling_point_used": ceiling_point,
        "dim1_spearman": dim1,
        "dim1_spearman_pct_of_ceiling": 100.0 * dim1 / ceiling_point,
        "dim1_spearman_arithmetic": f"{dim1:.4f} / {ceiling_point:.4f} * 100",
        "band_accuracy_overall": band,
        "band_accuracy_pct_of_ceiling": 100.0 * band / ceiling_point,
        "band_accuracy_arithmetic": f"{band:.4f} / {ceiling_point:.4f} * 100",
        "note": (
            "band_accuracy_overall (near/mid/far tier agreement -- the model's OWN band "
            "assignment vs the benchmark's tier) is the metric type directly comparable to "
            "this ceiling (also a near/mid/far tier-agreement rate). dim1_spearman is a rank "
            "correlation, a DIFFERENT metric type, shown per spec step 9's explicit request "
            "but not apples-to-apples with a tier-agreement ceiling -- reported for "
            "completeness, not cherry-picked."
        ),
    }


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------


def render_markdown(result: dict) -> str:
    lines = [
        "# LLM-consensus label ceiling -- spec-metrics-ceiling-calibration.md WORKSTREAM 2",
        "",
        f"**{LLM_CONSENSUS_CAVEAT}**",
        "",
        f"Judges: {', '.join(result['judges'])} | k={result['k_self_consistency']} "
        f"self-consistency samples/item, temperature={result['temperature']} | "
        f"seed={result['seed']}",
        f"Wall-clock: {result['wall_clock_seconds']:.1f}s",
        "",
        "## 1. Calibration gate (run first, mandatory)",
        "",
    ]
    passed, msg = calibration_verdict(result["calibration"])
    lines.append(f"**Verdict: {'PASS' if passed else 'FAIL'}** -- {msg}")
    lines.append("")
    lines.append("| judge | accuracy | near-control | far-control | n | bar | pass |")
    lines.append("|---|---|---|---|---|---|---|")
    for m, r in result["calibration"]["per_judge"].items():
        lines.append(
            f"| {m} | {r['accuracy']:.1%} | {r['near_accuracy']:.1%} | "
            f"{r['far_accuracy']:.1%} | {r['n_control_items']} | {r['bar']:.0%} | "
            f"{'PASS' if r['passed'] else 'FAIL'} |"
        )

    if not passed:
        lines += [
            "",
            "**Run stopped here -- the main-sample ceiling was NOT computed** "
            "(see verdict above). No third local model family is available to substitute a "
            "failing judge in this environment.",
            "",
        ]
        return "\n".join(lines) + "\n"

    kj = result["kappa"]
    lines += [
        "",
        "## 2. Inter-judge agreement (trust gate)",
        "",
        f"Cohen's linear-weighted kappa: **{kj['kappa']['point']:.4f}** "
        f"(95% CI {kj['kappa']['ci_95']}) -- Landis-Koch band: **{kj['landis_koch_band']}** "
        f"-- reliability verdict: **{'RELIABLE' if kj['reliable'] else 'UNRELIABLE'}**",
        f"Raw (unweighted) agreement rate: {kj['raw_agreement_rate']:.4f} | n pairs: "
        f"{kj['n_pairs']}",
        "",
        "Confusion matrix (rows=" + kj["confusion_matrix"]["rows_are"] + ", cols="
        + kj["confusion_matrix"]["cols_are"] + "):",
        "",
        "| | " + " | ".join(kj["confusion_matrix"]["categories"]) + " |",
        "|---|" + "---|" * len(kj["confusion_matrix"]["categories"]),
    ]
    cm_cats = kj["confusion_matrix"]["categories"]
    cm_matrix = kj["confusion_matrix"]["matrix"]
    for tier, row in zip(cm_cats, cm_matrix, strict=True):
        lines.append(f"| {tier} | " + " | ".join(str(c) for c in row) + " |")

    if not kj["reliable"]:
        lines += [
            "",
            "**WARNING: kappa is below the reliability threshold (0.4). The ceiling below "
            "must be treated as UNRELIABLE, not used as a firm number.**",
        ]

    ceil = result["ceiling"]
    lines += [
        "",
        "## 3. Contested items (disagreement handling)",
        "",
        f"n resolved (judges agreed): {ceil['n_resolved']} | n contested (judges "
        f"disagreed): {ceil['n_contested']} | n judge-unavailable: "
        f"{ceil['n_judge_unavailable']} | contested rate: "
        f"{ceil['contested_rate']:.1%}" if ceil["contested_rate"] is not None else "",
        "",
    ]
    if ceil["contested_examples"]:
        lines.append("Example contested items:")
        lines.append("")
        lines.append(f"| secret | word | benchmark tier | {JUDGE_MODELS[0]} | {JUDGE_MODELS[1]} |")
        lines.append("|---|---|---|---|---|")
        for ex in ceil["contested_examples"]:
            lines.append(
                f"| {ex['secret']} | {ex['word']} | {ex['benchmark_tier']} | "
                f"{ex[JUDGE_MODELS[0]]} | {ex[JUDGE_MODELS[1]]} |"
            )

    lines += [
        "",
        "## 4. Ceiling -- sensitivity analysis",
        "",
        "| tie-break rule | value | arithmetic | description |",
        "|---|---|---|---|",
    ]
    for _rule, s in ceil["sensitivity"].items():
        val = f"{s['value']:.4f}" if s["value"] is not None else "N/A"
        lines.append(f"| {_rule} | {val} | {s.get('arithmetic', '')} | {s['description']} |")

    perf = result["performance_vs_ceiling"]
    lines += [
        "",
        "## 5. Current shipped-model performance as % of ceiling",
        "",
        f"Ceiling point used (resolved-only, primary estimate): "
        f"{perf['ceiling_point_used']:.4f}",
        "",
        f"- dim1 Spearman: {perf['dim1_spearman']:.4f} -- "
        f"**{perf['dim1_spearman_pct_of_ceiling']:.1f}%** of ceiling "
        f"({perf['dim1_spearman_arithmetic']})",
        f"- band-tier accuracy (overall): {perf['band_accuracy_overall']:.4f} -- "
        f"**{perf['band_accuracy_pct_of_ceiling']:.1f}%** of ceiling "
        f"({perf['band_accuracy_arithmetic']})",
        "",
        perf["note"],
        "",
        "## Sample sizes and provenance",
        "",
        f"- Main ceiling sample: {result['main_sample_size']} items "
        "(prepare_label_ceiling_sample.py's same tier x domain stratified 75-item draw, "
        "seed=42)",
        f"- Calibration controls: {result['control_near_size']} near + "
        f"{result['control_far_size']} far = "
        f"{result['control_near_size'] + result['control_far_size']} items",
        f"- Ollama models verified live: {result['judges_verified']}",
        "",
        "---",
        "",
        f"**{LLM_CONSENSUS_CAVEAT}**",
        "",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


def run_full_protocol(
    per_tier_target: int = PER_TIER_TARGET,
    control_near_size: int = CONTROL_NEAR_SIZE,
    control_far_size: int = CONTROL_FAR_SIZE,
    k: int = K_SELF_CONSISTENCY,
    models: tuple[str, ...] = JUDGE_MODELS,
    seed: int = SEED,
    verbose: bool = True,
) -> dict:
    """Full 10-step protocol. `per_tier_target` (default PER_TIER_TARGET=25,
    i.e. the full 75-item sample across 3 tiers) is exposed as a CLI knob
    for fast smoke runs, not for silently shrinking the reported sample
    (see module __main__ CLI help)."""
    t0 = time.time()

    availability = verify_judges_available()
    missing = [m for m, ok in availability.items() if not ok]
    if missing:
        raise ConsensusJudgeUnavailableError(
            f"Judge model(s) not pulled: {missing}. Run `ollama pull <model>` for each."
        )

    main_sample = build_main_sample(per_tier_target=per_tier_target, seed=seed)
    main_keys = frozenset((it.secret, it.word) for it in main_sample)

    control_near = build_control_near(n=control_near_size, exclude=main_keys)
    control_far = build_control_far(n=control_far_size, seed=seed + 5000, exclude=main_keys)
    control_items = control_near + control_far

    calibration = run_calibration_gate(
        control_items, models=models, seed=seed, k=k, verbose=verbose
    )
    passed, _msg = calibration_verdict(calibration)

    result: dict = {
        "judges": list(models),
        "judges_verified": availability,
        "seed": seed,
        "temperature": TEMPERATURE,
        "k_self_consistency": k,
        "main_sample_size": len(main_sample),
        "control_near_size": len(control_near),
        "control_far_size": len(control_far),
        "calibration": calibration,
    }

    if not passed:
        result["kappa"] = None
        result["ceiling"] = None
        result["performance_vs_ceiling"] = None
        result["wall_clock_seconds"] = time.time() - t0
        return result

    main_result = run_main_sample(main_sample, models=models, seed=seed, k=k, verbose=verbose)
    kappa = compute_inter_judge_kappa(main_result["per_item"], models=models)
    ceiling = compute_ceiling(main_result["per_item"])
    current = load_current_state_metrics()
    perf = performance_as_pct_of_ceiling(current, ceiling["sensitivity"]["resolved_only"]["value"])

    result["main_sample_per_item"] = main_result["per_item"]
    result["main_sample_raw"] = main_result["raw"]  # full per-model, per-item self-consistency
    # vote lists (not just the collapsed majority) -- kept for downstream-synthesis provenance.
    result["kappa"] = kappa
    result["ceiling"] = ceiling
    result["current_state_metrics"] = current
    result["performance_vs_ceiling"] = perf
    result["wall_clock_seconds"] = time.time() - t0
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--main-sample-size",
        type=int,
        default=PER_TIER_TARGET,
        dest="per_tier_target",
        help="Per-tier target for the main sample (default 25 -> 75 total, the full spec sample).",
    )
    parser.add_argument("--control-size", type=int, default=CONTROL_NEAR_SIZE)
    parser.add_argument("--k", type=int, default=K_SELF_CONSISTENCY)
    args = parser.parse_args()

    result = run_full_protocol(
        per_tier_target=args.per_tier_target,
        control_near_size=args.control_size,
        control_far_size=args.control_size,
        k=args.k,
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(f"wrote {OUT_JSON} and {OUT_MD}")
    print(f"wall-clock: {result['wall_clock_seconds']:.1f}s")
    if result["kappa"] is not None:
        kappa_point = result["kappa"]["kappa"]["point"]
        band = result["kappa"]["landis_koch_band"]
        ceiling_point = result["ceiling"]["sensitivity"]["resolved_only"]["value"]
        print(f"kappa: {kappa_point:.4f} ({band})")
        print(f"ceiling (resolved-only): {ceiling_point:.4f}")


if __name__ == "__main__":
    main()
