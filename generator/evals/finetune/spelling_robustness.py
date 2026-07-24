from __future__ import annotations

"""
Spelling-variance robustness suite (spec-model-excellence.md WORKSTREAM C,
items 9 and 11) -- THE core USP candidate: "measurably spelling-invariant
romanized-Hinglish embeddings".

CRITICAL DESIGN INSIGHT (why this module exists at all): the shipped payload
pipeline already makes spelling variants work correctly for GAMEPLAY, but
only at the STRING/HASH layer -- normalize.py folds a typed variant to its
canonical spelling BEFORE any embedding lookup, and payload.py's alt_map
(lines 150-283) just copies the canonical word's already-computed
[rank, qsim] onto the variant's hash. The embedding matrix is computed ONCE
for the canonical vocab; a variant spelling's payload entry is NEVER a fresh
embedding. That means the actual embedding-level question -- "if this word
had been spelled the other way, would the MODEL'S semantic behaviour stay
the same?" -- has never been measured anywhere in this repo. This module
answers it by bypassing normalize.py/canonical_for() entirely and embedding
variant spellings DIRECTLY through the model, exactly as if they were the
canonical secret, then measuring the resulting rank/band drift.

Baseline reuse: the 42-secret / 379-scenario combined dim1 test set already
evaluated and checkpointed for the shipped model
(evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert.json)
is used AS-IS for the canonical (unperturbed) ranks/bands -- no re-embedding
of the canonical spelling. Only the VARIANT spellings are freshly embedded.

Three provenance-tagged sources for real/plausible spelling variants
(spec item 9, Category 1), plus three synthetic axes with full 42-secret
coverage (spec item 11, Category 2):

  1a. alias_in_training / alias_file_untrained_heldout -- vocab/hi-en-
      aliases.txt (29 canonical words / 39 aliases). IMPORTANT CORRECTION vs
      the task's framing: not every alias-file entry that touches one of the
      42 test secrets was actually trained on. assemble_data.alias_source()
      EXCLUDES any pair whose canonical word is a held-out (dev/test) secret
      (evals/finetune/split.py) -- and the 42 test secrets ARE held-out by
      definition. Empirically verified: of the 3 test secrets with alias-file
      coverage (bagicha, chaand, pahad), ZERO of their alias pairs appear in
      train_mnrl_pairs.jsonl's 32 "source": "alias" entries. So this module
      checks literal (anchor, positive) membership in the real training file
      rather than assuming alias-file presence implies training, and splits
      the alias source into two honestly-distinct provenance tags:
        - alias_in_training: pair verified present in train_mnrl_pairs.jsonl
          (source=alias) -- strong performance here is EXPECTED, not
          surprising, and is a sanity check, not evidence of generalisation.
        - alias_file_untrained_heldout: pair exists in the curated alias
          file but was excluded from training via the held-out-secret rule
          -- this is actually a second genuine held-out real-variant source
          (alongside aksharantar_heldout), just smaller and curated by hand
          rather than mined.
  1b. aksharantar_heldout -- the actual held-out measurement. Mined from
      evals/finetune/data/raw/aksharantar_hi.jsonl (1.3M real-world
      romanized/devanagari pairs): group romanizations by devanagari word,
      find the devanagari group(s) a test secret belongs to, and take that
      group's OTHER romanized spellings as genuine, non-hallucinated,
      not-in-training variants. Filtered by is_clean_variant (normalized
      Levenshtein distance <= 0.4 AND length ratio in [0.6, 1.6] --
      rejects English-gloss leaks, inflection forms, and noise).
  1c. llm_generated -- local Ollama qwen3:8b (same $0 client pattern as
      llm_augment.py, no paid API) fallback for test secrets with NEITHER
      alias-file NOR Aksharantar coverage. Explicitly lower-confidence: the
      model's own beliefs about plausible romanizations, not observed
      real-world usage. Same is_clean_variant noise filter applied.
  2.  casing / whitespace / typo -- synthetic, deterministic (seed=42),
      full 42-secret coverage. See casing_variants/whitespace_variants/
      typo_variants below.

Metrics per category (all bootstrap-CI'd, cluster-by-secret, N_BOOT=10000,
seed=42 -- mirrors evals/finetune/bootstrap_ci.py's existing pattern):
  - rank drift: |variant_rank - canonical_rank| per (secret, test word,
    variant); mean/median + the single worst-case example.
  - band-agreement rate: fraction of (secret, word, variant) triples whose
    band is identical under canonical vs. variant spelling.
  - top_weighted_correlation (evals.harness.metrics, already exists): a
    holistic per-(secret, variant) full-vocab drift signal -- computed
    between the canonical secret's full rank array (recomputed once per
    secret, cheap -- one embed+argsort, same cost as any dim1 resolution)
    and the variant's full rank array (fresh embedding), weighted toward
    words genuinely close to the secret in PRODUCTION (canonical_rank is
    the weight source), then averaged with a cluster-by-secret bootstrap CI.

Run (from generator/):
    uv run python -m evals.finetune.spelling_robustness
    uv run python -m evals.finetune.spelling_robustness --no-llm   # skip category 1c
"""

import argparse
import json
import random
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from config import VOCAB_DIR
from embeddings import cosine_similarities, embed_vocab
from evals.finetune.benchmark_bakeoff import load_combined_dim1_scenarios
from evals.finetune.collision_scan import hinglish_anchor_glosses, hinglish_sourced_words
from evals.finetune.eval_model import _model_override
from evals.harness.dimension1_ranking import _resolve_actuals
from evals.harness.metrics import top_weighted_correlation
from payload import levenshtein
from rival import band_for_rank
from vocab import load_hien_vocab

FINETUNE_DIR = Path(__file__).parent
DATA_DIR = FINETUNE_DIR / "data"
CHECKPOINT_PATH = DATA_DIR / "bakeoff_raw" / "gauravgandhi2411__hinglish-relatedness-sbert.json"
ALIASES_PATH = VOCAB_DIR / "hi-en-aliases.txt"
TRAIN_MNRL_PATH = DATA_DIR / "train_mnrl_pairs.jsonl"
AKSHARANTAR_PATH = DATA_DIR / "raw" / "aksharantar_hi.jsonl"
REPORT_JSON_PATH = DATA_DIR / "spelling_robustness_report.json"
REPORT_MD_PATH = DATA_DIR / "spelling_robustness_report.md"

SEED = 42
N_BOOT = 10000

K_AKSHARANTAR_MAX_PER_SECRET = 3
K_LLM_VARIANTS_PER_SECRET = 2
MAX_NORM_EDIT_DISTANCE = 0.4
LEN_RATIO_BOUNDS = (0.6, 1.6)

CATEGORY_ORDER = [
    "alias_in_training",
    "alias_file_untrained_heldout",
    "aksharantar_heldout",
    "llm_generated",
    "casing",
    "whitespace",
    "typo",
]

_ALPHABET = "abcdefghijklmnopqrstuvwxyz"

# ---------------------------------------------------------------------------
# Category 2 -- casing / whitespace / typo. Pure, deterministic (seed=42),
# full 42-secret coverage. No model/network dependency -- unit-testable.
# ---------------------------------------------------------------------------


def casing_variants(word: str, seed: int = SEED) -> dict[str, str]:
    """Title Case, UPPERCASE, and one deterministic mixed-case variant
    (per-character random flip, seeded on `f"{seed}:{word}:mixed_case"` so
    the result is independent of call order/iteration).
    """
    rng = random.Random(f"{seed}:{word}:mixed_case")
    mixed = "".join(ch.upper() if rng.random() < 0.5 else ch for ch in word)
    return {"title": word.title(), "upper": word.upper(), "mixed": mixed}


def whitespace_variants(word: str) -> dict[str, str]:
    """Leading+trailing padding (always applies); a doubled-internal-space
    variant only when `word` actually contains a space -- the 42 test
    secrets are all single tokens, so this sub-case is expected to never
    fire for them (verified empirically, noted in the report rather than
    forced).
    """
    variants = {"padded": f"  {word}  "}
    if " " in word:
        idx = word.index(" ")
        variants["doubled_internal_space"] = word[:idx] + "  " + word[idx + 1 :]
    return variants


def typo_variants(word: str, seed: int = SEED) -> dict[str, str]:
    """One substitution typo + one transposition-or-insertion typo, both
    single-edit-distance from `word`, deterministic per word via `seed`.

    Substitution: replace one randomly-chosen character with a different
    random lowercase letter.
    Transposition: swap two adjacent DISTINCT characters if such a pair
    exists; otherwise fall back to inserting one random lowercase letter at
    a random position (a word with no distinct-adjacent pair, e.g. "aaa",
    has no meaningful transposition).

    Returns {} for words shorter than 2 characters (neither operation is
    meaningful).
    """
    if len(word) < 2:
        return {}
    rng = random.Random(f"{seed}:{word}:typo")

    pos = rng.randrange(len(word))
    original_ch = word[pos]
    choices = [c for c in _ALPHABET if c != original_ch]
    new_ch = rng.choice(choices)
    substitution = word[:pos] + new_ch + word[pos + 1 :]

    adjacent_pairs = [i for i in range(len(word) - 1) if word[i] != word[i + 1]]
    if adjacent_pairs:
        i = rng.choice(adjacent_pairs)
        chars = list(word)
        chars[i], chars[i + 1] = chars[i + 1], chars[i]
        transposition_or_insertion = "".join(chars)
    else:
        ins_pos = rng.randrange(len(word) + 1)
        ins_ch = rng.choice(_ALPHABET)
        transposition_or_insertion = word[:ins_pos] + ins_ch + word[ins_pos:]

    return {"substitution": substitution, "transposition_or_insertion": transposition_or_insertion}


# ---------------------------------------------------------------------------
# Noise filter shared by the Aksharantar and LLM-generated sources.
# ---------------------------------------------------------------------------


def is_clean_variant(
    secret: str,
    candidate: str,
    max_norm_edit_distance: float = MAX_NORM_EDIT_DISTANCE,
    len_ratio_bounds: tuple[float, float] = LEN_RATIO_BOUNDS,
) -> bool:
    """True iff `candidate` plausibly a spelling variant of `secret` rather
    than noise (English-gloss leak, plural/inflection form, or unrelated
    word): normalized Levenshtein distance
    (payload.levenshtein(secret, candidate) / max(len)) must be
    <= max_norm_edit_distance, AND the raw length ratio
    len(candidate)/len(secret) must fall within len_ratio_bounds. An exact
    match to `secret` is rejected -- it carries no spelling-variance signal.
    """
    if not secret or not candidate or candidate == secret:
        return False
    norm_dist = levenshtein(secret, candidate) / max(len(secret), len(candidate))
    if norm_dist > max_norm_edit_distance:
        return False
    ratio = len(candidate) / len(secret)
    lo, hi = len_ratio_bounds
    return lo <= ratio <= hi


# ---------------------------------------------------------------------------
# Category 1a -- alias-file variants, split by verified training membership.
# ---------------------------------------------------------------------------


def parse_alias_file(path: Path) -> dict[str, list[str]]:
    """{canonical: [alias1, alias2, ...]} straight from vocab/hi-en-
    aliases.txt, RAW spellings as written (NOT normalize()'d) -- this eval
    embeds variants directly, so the as-typed spelling is what matters.
    Mirrors assemble_data.alias_source()'s parsing (comment-stripping,
    canonical/alias split) but returns the grouped shape.
    """
    out: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        canonical_raw, aliases_raw = line.split(":", 1)
        canonical = canonical_raw.strip().lower()
        aliases = [a.strip().lower() for a in aliases_raw.split(",") if a.strip()]
        out.setdefault(canonical, []).extend(aliases)
    return out


def trained_alias_pairs(path: Path) -> set[tuple[str, str]]:
    """{(anchor, positive)} pairs LITERALLY present in train_mnrl_pairs.jsonl
    tagged source=="alias" -- the empirical ground truth for "was this exact
    alias pair actually trained on". assemble_data.alias_source() excludes
    any pair whose canonical OR alias touches a held-out (dev/test) secret
    (evals/finetune/split.py), so alias-file PRESENCE alone does not imply
    training membership -- see module docstring's correction.
    """
    out: set[tuple[str, str]] = set()
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("source") == "alias":
            out.add((rec["anchor"], rec["positive"]))
    return out


def split_alias_variants_by_training(
    secrets: list[str],
    alias_map: dict[str, list[str]],
    trained_pairs: set[tuple[str, str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Partition each secret's alias-file variants into (trained, untrained)
    using literal (secret, alias) membership in `trained_pairs`. Pure --
    testable with synthetic maps."""
    trained: dict[str, list[str]] = {}
    untrained: dict[str, list[str]] = {}
    for s in secrets:
        for alias in alias_map.get(s, []):
            bucket = trained if (s, alias) in trained_pairs else untrained
            bucket.setdefault(s, []).append(alias)
    return trained, untrained


# ---------------------------------------------------------------------------
# Category 1b -- Aksharantar-mined held-out variants.
# ---------------------------------------------------------------------------


def build_aksharantar_maps(path: Path) -> tuple[dict[str, set[str]], dict[str, Counter[str]]]:
    """Single pass over aksharantar_hi.jsonl (1.3M real-world mined pairs)
    building:
      - rom_to_deva: {romanized_lower: {devanagari, ...}} -- which
        devanagari word(s) this romanized spelling was observed for.
      - deva_to_rom: {devanagari: Counter({romanized_lower: count})} -- all
        romanized spellings observed for that devanagari word, weighted by
        occurrence count.
    Malformed/empty-field lines are skipped, not fatal.
    """
    rom_to_deva: dict[str, set[str]] = defaultdict(set)
    deva_to_rom: dict[str, Counter[str]] = defaultdict(Counter)
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            deva = (rec.get("devanagari") or "").strip()
            rom = (rec.get("romanized") or "").strip().lower()
            if not deva or not rom:
                continue
            rom_to_deva[rom].add(deva)
            deva_to_rom[deva][rom] += 1
    return dict(rom_to_deva), dict(deva_to_rom)


def aksharantar_variants_for_secret(
    secret: str,
    rom_to_deva: dict[str, set[str]],
    deva_to_rom: dict[str, Counter[str]],
    max_variants: int = K_AKSHARANTAR_MAX_PER_SECRET,
) -> list[str]:
    """Real-world alternate romanized spellings of `secret`: find every
    devanagari word `secret` was observed romanizing to, gather every OTHER
    romanized spelling observed for those same devanagari word(s), keep
    only the ones passing is_clean_variant, rank by observed frequency
    (most-attested first, ties broken alphabetically for determinism), cap
    at `max_variants`.
    """
    devas = rom_to_deva.get(secret, set())
    if not devas:
        return []
    candidates: Counter[str] = Counter()
    for deva in devas:
        candidates.update(deva_to_rom.get(deva, Counter()))
    clean = [w for w in candidates if is_clean_variant(secret, w)]
    clean.sort(key=lambda w: (-candidates[w], w))
    return clean[:max_variants]


def aksharantar_full_vocab_coverage(
    rom_to_deva: dict[str, set[str]], deva_to_rom: dict[str, Counter[str]]
) -> dict:
    """Honest coverage stat (spec item 1c "report the coverage honestly"):
    of the full ~544-word hinglish-sourced vocab (not just the 42 test
    secrets), how many have >=1 clean Aksharantar-mined variant?
    """
    hi_words = sorted(hinglish_sourced_words())
    covered = [
        w
        for w in hi_words
        if aksharantar_variants_for_secret(w, rom_to_deva, deva_to_rom, max_variants=1)
    ]
    return {
        "n_hinglish_vocab_words": len(hi_words),
        "n_with_clean_aksharantar_variant": len(covered),
        "pct_with_clean_aksharantar_variant": (len(covered) / len(hi_words)) if hi_words else None,
    }


# ---------------------------------------------------------------------------
# Category 1c -- local-Ollama LLM-generated fallback (lower confidence).
# ---------------------------------------------------------------------------

_SPELLING_VARIANT_PROMPT = """The word "{word}" is a romanized Hindi/Hinglish word (English \
gloss: "{gloss}"). Real-world speakers write this word with different spellings because \
romanization of Hindi into Latin script is inconsistent (long vowels, aspirated consonants, \
etc). Give up to {n} DIFFERENT plausible alternate romanized spellings of "{word}" that a \
Hindi-English speaker might actually type -- NOT the same spelling, NOT English synonyms, NOT \
translations, just alternate ROMANIZATIONS of the SAME Hindi word.

Respond with ONLY a JSON array of lowercase strings, no other text, no markdown fences:
["...", "..."]"""

_OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"


def ollama_reachable(timeout: float = 3.0) -> bool:
    """Cheap reachability check for the local Ollama server -- used to
    decide up front whether category 1c can run at all, so the pipeline can
    report "skipped, Ollama unavailable" instead of silently returning an
    empty category with no explanation.
    """
    try:
        with urllib.request.urlopen(_OLLAMA_TAGS_URL, timeout=timeout):  # noqa: S310
            return True
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


def _call_ollama_for_variants(word: str, gloss: str, n: int) -> list[str]:
    """One Ollama generation call (local qwen3:8b, $0, no API key -- same
    client/isolation pattern as llm_augment.py, whose low-level HTTP helper
    is reused directly rather than reimplemented). Returns a raw candidate
    list; caller cleans/filters via is_clean_variant.
    """
    from evals.finetune.llm_augment import LLMUnavailableError, _call_ollama

    prompt = _SPELLING_VARIANT_PROMPT.format(word=word, gloss=gloss or word, n=n)
    schema = {"type": "array", "items": {"type": "string"}}
    try:
        raw = _call_ollama(prompt, response_format=schema)
    except (LLMUnavailableError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [w.strip().lower() for w in raw if isinstance(w, str) and w.strip()]


def llm_variants_for_secret(word: str, gloss: str, n: int = K_LLM_VARIANTS_PER_SECRET) -> list[str]:
    """Clean + filter one secret's raw LLM-generated candidates through the
    SAME is_clean_variant noise filter as the Aksharantar source, deduped,
    capped at `n`. Explicitly a LOWER-CONFIDENCE source than
    aksharantar_heldout -- the model's own beliefs about plausible
    romanizations, not observed real-world usage (see module docstring,
    category 1c).
    """
    raw = _call_ollama_for_variants(word, gloss, n=n)
    seen: set[str] = set()
    out: list[str] = []
    for w in raw:
        if w not in seen and is_clean_variant(word, w):
            seen.add(w)
            out.append(w)
    return out[:n]


# ---------------------------------------------------------------------------
# Embedding primitives -- bypass normalize.py/canonical_for() AND
# embeddings.embed_vocab's persistent (model_name, vocab)-keyed disk cache
# entirely (every call here has a different, one-off vocab that only exists
# for the duration of this script -- caching would only bloat .model-cache
# with hundreds of never-reused single/few-word .npy files).
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict[str, object] = {}


def _get_sentence_transformer(model_name: str):
    """Load-once, reuse-many model instance cache -- avoids reloading the
    checkpoint from disk for every single variant embed call."""
    if model_name not in _MODEL_CACHE:
        import os

        from sentence_transformers import SentenceTransformer

        _MODEL_CACHE[model_name] = SentenceTransformer(model_name, token=os.environ.get("HF_TOKEN"))
    return _MODEL_CACHE[model_name]


def embed_words_direct(words: list[str], model_name: str) -> NDArray[np.float32]:
    """Embed `words` DIRECTLY through `model_name` -- the core robustness-
    eval primitive: it answers "what does the model do with THIS exact
    string", not "what does the payload pipeline do after alias-folding".
    Mirrors embeddings.embed_vocab's `model.encode(..., normalize_
    embeddings=True)` call + belt-and-suspenders renormalization exactly,
    minus the disk cache (see module-section docstring above).
    """
    model = _get_sentence_transformer(model_name)
    raw: NDArray[np.float32] = model.encode(words, convert_to_numpy=True, normalize_embeddings=True)
    matrix = raw.astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (matrix / norms).astype(np.float32)


def full_rank_table(
    matrix: NDArray[np.float32], query_vec: NDArray[np.float32]
) -> NDArray[np.int32]:
    """1-based rank of every vocab row against `query_vec` -- identical
    pattern to dimension1_ranking._resolve_actuals's inner loop (lines
    63-69) / payload._build_payload_core's rank computation, factored into
    a standalone reusable function since this module calls it once per
    SECRET (canonical) and once per (secret, variant) PAIR, not just once
    per secret like the production callers.
    """
    sims = cosine_similarities(matrix, query_vec)
    order = np.argsort(-sims)
    ranks = np.empty(len(matrix), dtype=np.int32)
    for rank_minus1, idx in enumerate(order):
        ranks[idx] = rank_minus1 + 1
    return ranks


# ---------------------------------------------------------------------------
# Drift computation -- PURE given synthetic rank data (no numpy/model
# dependency in this function itself), independently unit-testable.
# ---------------------------------------------------------------------------


def compute_variant_drift(
    secret: str,
    category: str,
    variant_label: str,
    variant_word: str,
    canonical_word_records: list[dict],
    variant_rank_by_word: dict[str, int],
    vocab_size: int,
) -> list[dict]:
    """For every (word, tier, actual_rank, actual_band) record belonging to
    `secret` in the canonical (unperturbed) checkpoint, look up that same
    word's rank under the variant spelling (`variant_rank_by_word`) and
    compute rank_drift + band agreement. Words missing from
    `variant_rank_by_word` are skipped (never silently treated as
    zero-drift).
    """
    out: list[dict] = []
    for rec in canonical_word_records:
        word = rec["word"]
        if word not in variant_rank_by_word or rec["actual_rank"] is None:
            continue
        v_rank = variant_rank_by_word[word]
        v_band = band_for_rank(v_rank, vocab_size)
        out.append(
            {
                "category": category,
                "secret": secret,
                "variant_label": variant_label,
                "variant_word": variant_word,
                "word": word,
                "tier": rec["tier"],
                "canonical_rank": rec["actual_rank"],
                "canonical_band": rec["actual_band"],
                "variant_rank": v_rank,
                "variant_band": v_band,
                "rank_drift": abs(v_rank - rec["actual_rank"]),
                "band_agree": v_band == rec["actual_band"],
            }
        )
    return out


def top_weighted_correlation_for_variant(
    canonical_ranks: NDArray[np.int32], variant_ranks: NDArray[np.int32]
) -> float:
    """Holistic full-vocab drift signal for one (secret, variant) pair:
    evals.harness.metrics.top_weighted_correlation, weighted toward words
    that are genuinely close to the secret in PRODUCTION -- canonical_ranks
    is passed as the `actual_rank` argument (the weight source / ground
    truth of what ships to users today), variant_ranks as `expected_ordinal`
    (the hypothesis under test: does the model preserve this ranking under
    a spelling perturbation?). This concentrates weight on words users
    actually perceive near the top of the REAL ranking, not tail noise.
    """
    return top_weighted_correlation(variant_ranks.tolist(), canonical_ranks.tolist())


# ---------------------------------------------------------------------------
# Aggregation + bootstrap CIs (cluster by secret, N_BOOT=10000, seed=42 --
# mirrors evals/finetune/bootstrap_ci.py's existing pattern).
# ---------------------------------------------------------------------------


def aggregate_drift_records(records: list[dict]) -> dict:
    """n, band-agreement rate, mean/median rank drift, and the single
    worst-case (max rank_drift) record for one flat list of drift records
    (already filtered to one category)."""
    if not records:
        return {
            "n": 0,
            "band_agreement_rate": None,
            "mean_rank_drift": None,
            "median_rank_drift": None,
            "worst_case": None,
        }
    drifts = [r["rank_drift"] for r in records]
    agree = [r["band_agree"] for r in records]
    worst = max(records, key=lambda r: r["rank_drift"])
    return {
        "n": len(records),
        "band_agreement_rate": sum(agree) / len(agree),
        "mean_rank_drift": float(np.mean(drifts)),
        "median_rank_drift": float(np.median(drifts)),
        "worst_case": worst,
    }


def _by_secret(records: list[dict]) -> dict[str, list[dict]]:
    by_secret: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_secret[r["secret"]].append(r)
    return dict(by_secret)


def _percentile_ci(draws: list[float]) -> list[float] | None:
    if len(draws) < 2:
        return None
    return [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))]


def bootstrap_drift_ci(records: list[dict], n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Cluster-by-secret bootstrap CI on band_agreement_rate and
    mean_rank_drift: resample secret NAMES with replacement (same pattern
    as evals.finetune.bootstrap_ci's dim1/topheavy helpers), pool each
    draw's records, recompute the point statistics.
    """
    point = aggregate_drift_records(records)
    by_secret = _by_secret(records)
    secrets = sorted(by_secret)
    if not secrets:
        return {
            "n": 0,
            "n_clusters": 0,
            "band_agreement_rate": {"point": None, "ci_95": None, "n_valid_bootstrap_draws": 0},
            "mean_rank_drift": {"point": None, "ci_95": None, "n_valid_bootstrap_draws": 0},
            "median_rank_drift": None,
            "worst_case": None,
        }
    rng = np.random.default_rng(seed)
    agree_draws: list[float] = []
    drift_draws: list[float] = []
    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        recs = [r for s in resample for r in by_secret[s]]
        if not recs:
            continue
        agree_draws.append(sum(r["band_agree"] for r in recs) / len(recs))
        drift_draws.append(float(np.mean([r["rank_drift"] for r in recs])))
    return {
        "n": point["n"],
        "n_clusters": len(secrets),
        "band_agreement_rate": {
            "point": point["band_agreement_rate"],
            "ci_95": _percentile_ci(agree_draws),
            "n_valid_bootstrap_draws": len(agree_draws),
        },
        "mean_rank_drift": {
            "point": point["mean_rank_drift"],
            "ci_95": _percentile_ci(drift_draws),
            "n_valid_bootstrap_draws": len(drift_draws),
        },
        "median_rank_drift": point["median_rank_drift"],
        "worst_case": point["worst_case"],
    }


def bootstrap_scalar_mean_ci(
    values_by_secret: dict[str, list[float]], n_boot: int = N_BOOT, seed: int = SEED
) -> dict:
    """Generic cluster-by-secret bootstrap CI on the mean of a list of
    per-(secret, variant) scalars -- used for top_weighted_correlation.
    NaN values (undefined correlation, e.g. zero variance) are dropped, not
    zero-filled.
    """
    secrets = sorted(values_by_secret)
    if not secrets:
        return {"point": None, "ci_95": None, "n_clusters": 0, "n_valid_bootstrap_draws": 0}
    all_vals = [v for s in secrets for v in values_by_secret[s] if not np.isnan(v)]
    point = float(np.mean(all_vals)) if all_vals else None
    rng = np.random.default_rng(seed)
    draws: list[float] = []
    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        vals = [v for s in resample for v in values_by_secret[s] if not np.isnan(v)]
        if vals:
            draws.append(float(np.mean(vals)))
    return {
        "point": point,
        "ci_95": _percentile_ci(draws),
        "n_clusters": len(secrets),
        "n_valid_bootstrap_draws": len(draws),
    }


# ---------------------------------------------------------------------------
# Full pipeline.
# ---------------------------------------------------------------------------


def _load_checkpoint() -> dict:
    if not CHECKPOINT_PATH.exists():
        raise FileNotFoundError(
            f"{CHECKPOINT_PATH} not found -- run "
            "`uv run python -m evals.finetune.benchmark_bakeoff --model "
            '"gauravgandhi2411/hinglish-relatedness-sbert"` first'
        )
    return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))


def build_report(include_llm: bool = True, model_override: str | None = None) -> tuple[str, dict]:
    """Full I/O-driving pipeline: load the canonical checkpoint, generate
    every category's variant spellings, embed them all in one batch, compute
    per-(secret, word, variant) drift + per-(secret, variant) holistic
    correlation, aggregate with bootstrap CIs, render markdown + JSON.

    `model_override` (spec-model-excellence.md WORKSTREAM C, item 10 --
    gating a variant-augmented retraining candidate): when given, the SAME
    test-secret set + variant-generation logic runs, but BOTH the canonical
    (unperturbed) ranks/bands AND every variant's ranks/bands are freshly
    computed under `model_override` instead of reusing the shipped
    checkpoint's canonical_records -- comparing a candidate model's variant
    embedding against the SHIPPED model's canonical embedding would conflate
    "candidate behaves differently" with "candidate is more spelling-
    invariant". `model_override=None` (default) preserves the original
    behaviour exactly: canonical ranks/bands reused as-is from the shipped
    checkpoint, matching this module's original design note (module
    docstring, "Baseline reuse"). The fresh-computation path uses
    benchmark_bakeoff.load_combined_dim1_scenarios + dimension1_ranking.
    _resolve_actuals -- the SAME combined 42-secret (8 production + 34
    benchmark-supplement) resolution benchmark_bakeoff.evaluate_one_model
    used to build the shipped checkpoint in the first place; eval_model.
    dim1_for_secrets alone only covers the 8 production-fixture test
    secrets and silently omits the 34 supplement secrets (e.g. "azaadi"),
    which would leave canonical_by_secret missing entries the rest of this
    function's test_secrets loop expects.
    """
    checkpoint = _load_checkpoint()
    test_secrets = sorted({r["secret"] for r in checkpoint["dim1_records"]})
    if model_override is not None:
        model_name = model_override
        with _model_override(model_name):
            raw_scenarios = load_combined_dim1_scenarios(set(test_secrets))
            canonical_records_all = _resolve_actuals(raw_scenarios, "hi-en")
    else:
        model_name = checkpoint["model"]
        canonical_records_all = checkpoint["dim1_records"]
    canonical_by_secret = _by_secret(canonical_records_all)

    vocab = load_hien_vocab()
    with _model_override(model_name):
        matrix = embed_vocab(vocab, "hi-en")
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    n = len(vocab)

    canonical_rank_tables: dict[str, NDArray[np.int32]] = {}
    for s in test_secrets:
        if s in word_to_idx:
            canonical_rank_tables[s] = full_rank_table(matrix, matrix[word_to_idx[s]])

    # --- category 2: casing / whitespace / typo -- full 42-secret coverage
    casing = {s: casing_variants(s) for s in test_secrets}
    whitespace = {s: whitespace_variants(s) for s in test_secrets}
    n_secrets_with_internal_space = sum(1 for s in test_secrets if " " in s)
    typo = {s: v for s in test_secrets if (v := typo_variants(s))}

    # --- category 1a: alias-file variants, split by verified training ---
    alias_map = parse_alias_file(ALIASES_PATH)
    trained_pairs = trained_alias_pairs(TRAIN_MNRL_PATH)
    alias_trained, alias_untrained = split_alias_variants_by_training(
        test_secrets, alias_map, trained_pairs
    )

    # --- category 1b: Aksharantar-mined held-out variants ---
    rom_to_deva, deva_to_rom = build_aksharantar_maps(AKSHARANTAR_PATH)
    aksharantar: dict[str, list[str]] = {}
    for s in test_secrets:
        variants = aksharantar_variants_for_secret(s, rom_to_deva, deva_to_rom)
        if variants:
            aksharantar[s] = variants
    coverage_stats = aksharantar_full_vocab_coverage(rom_to_deva, deva_to_rom)

    # --- category 1c: local-Ollama fallback for secrets with no real coverage
    covered = {s for s in test_secrets if alias_map.get(s) or aksharantar.get(s)}
    uncovered = sorted(set(test_secrets) - covered)
    glosses = hinglish_anchor_glosses()
    llm_available = include_llm and ollama_reachable()
    llm_variants: dict[str, list[str]] = {}
    if llm_available:
        for s in uncovered:
            variants = llm_variants_for_secret(s, glosses.get(s, s))
            if variants:
                llm_variants[s] = variants

    # --- gather every variant string across every category, embed once ---
    all_words: set[str] = set()
    for mapping in (casing, whitespace):
        for variants in mapping.values():
            all_words.update(variants.values())
    for mapping in (typo,):
        for variants in mapping.values():
            all_words.update(variants.values())
    for mapping in (alias_trained, alias_untrained, aksharantar, llm_variants):
        for variants in mapping.values():
            all_words.update(variants)

    word_list = sorted(all_words)
    vec_lookup: dict[str, NDArray[np.float32]] = {}
    if word_list:
        vecs = embed_words_direct(word_list, model_name)
        vec_lookup = {w: vecs[i] for i, w in enumerate(word_list)}

    all_drift_records: list[dict] = []
    twc_by_category: dict[str, dict[str, list[float]]] = {
        cat: defaultdict(list) for cat in CATEGORY_ORDER
    }

    def _process(category: str, mapping: dict[str, dict[str, str]]) -> None:
        for s, variants in mapping.items():
            if s not in canonical_rank_tables:
                continue
            words_needed = {r["word"] for r in canonical_by_secret.get(s, [])}
            for label, word in variants.items():
                if word not in vec_lookup:
                    continue
                v_ranks = full_rank_table(matrix, vec_lookup[word])
                variant_rank_by_word = {
                    w: int(v_ranks[word_to_idx[w]]) for w in words_needed if w in word_to_idx
                }
                drift_recs = compute_variant_drift(
                    s, category, label, word, canonical_by_secret[s], variant_rank_by_word, n
                )
                all_drift_records.extend(drift_recs)
                twc = top_weighted_correlation_for_variant(canonical_rank_tables[s], v_ranks)
                twc_by_category[category][s].append(twc)

    _process("casing", casing)
    _process("whitespace", whitespace)
    _process("typo", typo)
    _process("alias_in_training", _labelled_map(alias_trained))
    _process("alias_file_untrained_heldout", _labelled_map(alias_untrained))
    _process("aksharantar_heldout", _labelled_map(aksharantar))
    _process("llm_generated", _labelled_map(llm_variants))

    summary: dict[str, dict] = {}
    for cat in CATEGORY_ORDER:
        recs = [r for r in all_drift_records if r["category"] == cat]
        drift_ci = bootstrap_drift_ci(recs)
        twc_ci = bootstrap_scalar_mean_ci(dict(twc_by_category[cat]))
        summary[cat] = {"drift": drift_ci, "top_weighted_correlation": twc_ci}

    verdict = _build_verdict(summary)

    report = {
        "model": model_name,
        "n_test_secrets": len(test_secrets),
        "test_secrets": test_secrets,
        "n_secrets_with_internal_space": n_secrets_with_internal_space,
        "llm_available": llm_available,
        "n_secrets_llm_fallback": len(llm_variants),
        "n_secrets_uncovered_no_real_variant": len(uncovered),
        "aksharantar_full_vocab_coverage": coverage_stats,
        "summary": summary,
        "verdict": verdict,
        "all_drift_records": all_drift_records,
    }
    md = _render_markdown(report)
    return md, report


def _labelled_map(mapping: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    """{secret: [v1, v2, ...]} -> {secret: {"v1": v1, "v2": v2, ...}} -- the
    shape _process expects (variant_label -> variant_word), labelling each
    real/LLM-generated variant by its own spelling (there's no more
    meaningful label than the string itself for these sources, unlike
    casing/whitespace/typo's named sub-variants).
    """
    return {s: {w: w for w in words} for s, words in mapping.items()}


def _build_verdict(summary: dict[str, dict]) -> dict:
    """Top-line verdict: is the model measurably spelling-invariant on
    HELD-OUT variants? aksharantar_heldout is the category that actually
    answers this (spec-mandated framing) -- alias_in_training is a sanity
    check, not evidence of generalisation.
    """
    aksh = summary["aksharantar_heldout"]["drift"]
    alias_untrained = summary["alias_file_untrained_heldout"]["drift"]
    n_aksh = aksh["n"]
    n_alias_untrained = alias_untrained["n"]
    n_real_heldout = n_aksh + n_alias_untrained

    thin_coverage = n_real_heldout < 20  # informal threshold -- see report text for the honest read
    band_agree = aksh["band_agreement_rate"]["point"]

    if n_real_heldout == 0:
        text = (
            "INCONCLUSIVE: zero held-out real spelling-variant pairs were found among the 42 "
            "test secrets (no aksharantar_heldout or alias_file_untrained_heldout coverage). "
            "The synthetic casing/whitespace/typo categories still measure robustness but "
            "cannot answer the specific 'does spelling-invariance hold on REAL romanization "
            "variants' question. Widen coverage (llm_generated is a lower-confidence stand-in) "
            "before treating any spelling-invariance claim as evidenced."
        )
    elif thin_coverage:
        text = (
            f"THIN BUT DIRECTIONAL: only n={n_real_heldout} held-out real-variant pairs "
            f"(aksharantar_heldout n={n_aksh}, alias_file_untrained_heldout n={n_alias_untrained}) "
            "were available among the 42 test secrets -- consistent with the a-priori estimate "
            "that Aksharantar-clean-pair coverage of this specific 42-secret set would be small. "
            "The bootstrap CI width on band-agreement-rate below is the honest signal of how much "
            "weight this result can bear; a wide CI means 'not enough held-out data to claim "
            "spelling-invariance with confidence', not 'the model fails'. See llm_generated for a "
            "lower-confidence larger-n supplement."
        )
    elif band_agree is not None and band_agree >= 0.8:
        text = (
            f"SUPPORTED: aksharantar_heldout band-agreement-rate={band_agree:.3f} with n={n_aksh} "
            "genuinely held-out real-world spelling variants -- the model's rank/band behaviour is "
            "reasonably stable on variants it was never trained on. Workstream C item 10 "
            "(variant-augmented retraining) is NOT urgently warranted on this evidence alone, "
            "though the small n means a confirming re-run after widening coverage is still "
            "worthwhile."
        )
    else:
        text = (
            f"NOT SUPPORTED: aksharantar_heldout band-agreement-rate="
            f"{band_agree if band_agree is not None else 'n/a'} with n={n_aksh} held-out real "
            "spelling variants -- robustness degrades meaningfully outside the trained alias "
            "words. Workstream C item 10 (variant-augmented contrastive retraining) IS warranted."
        )

    return {
        "n_real_heldout_pairs": n_real_heldout,
        "n_aksharantar_heldout": n_aksh,
        "n_alias_file_untrained_heldout": n_alias_untrained,
        "aksharantar_band_agreement_rate": band_agree,
        "thin_coverage": thin_coverage,
        "text": text,
    }


# ---------------------------------------------------------------------------
# Markdown rendering.
# ---------------------------------------------------------------------------


def _fmt_ci(leaf: dict | None) -> str:
    if leaf is None or leaf["point"] is None:
        return "n/a"
    if leaf["ci_95"] is None:
        return f"{leaf['point']:.3f} [no CI, n_draws<2]"
    lo, hi = leaf["ci_95"]
    return f"{leaf['point']:.3f} [{lo:.3f}, {hi:.3f}]"


def _fmt_worst(worst: dict | None) -> str:
    if worst is None:
        return "n/a"
    return (
        f"secret={worst['secret']!r} word={worst['word']!r} variant_word={worst['variant_word']!r} "
        f"({worst['category']}/{worst['variant_label']}): canonical_rank={worst['canonical_rank']} "
        f"(band {worst['canonical_band']}) -> variant_rank={worst['variant_rank']} "
        f"(band {worst['variant_band']}), drift={worst['rank_drift']}"
    )


_CATEGORY_CAVEAT = {
    "alias_in_training": (
        "SANITY CHECK ONLY -- these exact pairs were in the shipped model's training data "
        "(verified via literal membership in train_mnrl_pairs.jsonl). Strong performance here is "
        "expected and must NOT be used to support a spelling-invariance claim on its own."
    ),
    "alias_file_untrained_heldout": (
        "Curated real variant, excluded from training via the held-out-secret rule -- genuine "
        "held-out evidence, alongside aksharantar_heldout."
    ),
    "aksharantar_heldout": (
        "THE actual held-out measurement -- real-world mined variants, never trained on. This is "
        "the category that answers 'is the model spelling-invariant on words it wasn't trained "
        "for'."
    ),
    "llm_generated": (
        "LOWER CONFIDENCE -- the LLM's own beliefs about plausible romanizations, not observed "
        "real-world usage. Used only for secrets lacking both alias and Aksharantar coverage."
    ),
    "casing": "Synthetic, full 42-secret coverage.",
    "whitespace": (
        "Synthetic, full 42-secret coverage (internal-space sub-case only when applicable)."
    ),
    "typo": "Synthetic, full 42-secret coverage.",
}


def _render_markdown(report: dict) -> str:
    lines = [
        "# Spelling-variance robustness report",
        "",
        f"Model: `{report['model']}`. Test secrets: {report['n_test_secrets']} "
        "(evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert.json's "
        "checkpointed canonical ranks -- reused, not recomputed).",
        "",
        f"Ollama available: {report['llm_available']}. Secrets with no real (alias/Aksharantar) "
        f"coverage: {report['n_secrets_uncovered_no_real_variant']} "
        f"(llm_generated fallback produced usable variants for {report['n_secrets_llm_fallback']} "
        "of them).",
        "",
        f"Aksharantar full-vocab coverage (context, not the eval itself): "
        f"{report['aksharantar_full_vocab_coverage']['n_with_clean_aksharantar_variant']}/"
        f"{report['aksharantar_full_vocab_coverage']['n_hinglish_vocab_words']} hinglish-sourced "
        "vocab words have >=1 clean Aksharantar-mined variant.",
        "",
        f"Secrets with an internal space (whitespace 'doubled_internal_space' sub-case applies): "
        f"{report['n_secrets_with_internal_space']}/{report['n_test_secrets']}.",
        "",
        "## Summary table",
        "",
        "| category | n pairs | band-agreement rate [95% CI] | mean rank drift [95% CI] | "
        "median rank drift | top-weighted corr [95% CI] |",
        "|---|---|---|---|---|---|",
    ]
    for cat in CATEGORY_ORDER:
        s = report["summary"][cat]
        drift = s["drift"]
        twc = s["top_weighted_correlation"]
        median_val = drift["median_rank_drift"]
        median = f"{median_val:.1f}" if median_val is not None else "n/a"
        lines.append(
            f"| {cat} | {drift['n']} | {_fmt_ci(drift['band_agreement_rate'])} | "
            f"{_fmt_ci(drift['mean_rank_drift'])} | {median} | {_fmt_ci(twc)} |"
        )

    lines += ["", "## Worst-case example per category", ""]
    for cat in CATEGORY_ORDER:
        worst = report["summary"][cat]["drift"]["worst_case"]
        lines.append(f"- **{cat}**: {_fmt_worst(worst)}")
        lines.append(f"  - _{_CATEGORY_CAVEAT[cat]}_")

    v = report["verdict"]
    band_agree_str = (
        f"{v['aksharantar_band_agreement_rate']:.3f}"
        if v["aksharantar_band_agreement_rate"] is not None
        else "n/a"
    )
    lines += [
        "",
        "## Verdict",
        "",
        v["text"],
        "",
        f"(n_real_heldout_pairs={v['n_real_heldout_pairs']}, "
        f"n_aksharantar_heldout={v['n_aksharantar_heldout']}, "
        f"n_alias_file_untrained_heldout={v['n_alias_file_untrained_heldout']}, "
        f"aksharantar band-agreement-rate={band_agree_str})",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-llm", action="store_true", help="Skip category 1c even if Ollama is reachable"
    )
    args = parser.parse_args()

    md, report = build_report(include_llm=not args.no_llm)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_MD_PATH.write_text(md, encoding="utf-8")
    REPORT_JSON_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(md)
    print(f"wrote {REPORT_MD_PATH} and {REPORT_JSON_PATH}")


if __name__ == "__main__":
    main()
