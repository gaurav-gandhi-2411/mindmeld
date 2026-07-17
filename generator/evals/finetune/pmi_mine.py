from __future__ import annotations

"""
Corpus co-occurrence (PMI) relatedness mining — the "empirical relatedness
from real Hinglish/Hindi text" source called for in spec-hinglish-finetune.md
(WordSim-353-style: relatedness scores derived from real corpus statistics,
not hand-labeled synonymy). STAGING ONLY — this module writes
data/raw/corpus_pmi_pairs.jsonl and does NOT touch assemble_data.py or any
frozen training file. A human/orchestrator reviews the output before it is
wired into the training set.

Why this exists (see fetch_corpus_data.py's docstring and
data/translit_verification.json for the full finding): Aksharantar's Hindi
split is mostly mined from compound/inflected running text and systematically
lacks coverage of exactly the short common bare-stem words this game needs
(0/20 direct hits on a spot-check). This module works around that gap by
resolving Devanagari spellings via a dict-primary/LLM-fallback pattern, with a
mandatory corpus-occurrence gate so an LLM hallucination can never become an
anchor for co-occurrence mining.

Pipeline (spec-hinglish-finetune.md addendum, "corpus PMI mining"):
  1. Anchor vocabulary: vocab/hinglish.txt words minus held-out secrets/
     translations (split.py). Each anchor's Devanagari spelling comes from
     inverting Aksharantar's raw pairs (highest pair-frequency wins) or, for
     the majority with no dict coverage, a batched local Ollama qwen3:8b call.
     Every candidate Devanagari spelling must occur >=3 times as a token in
     the IndicCorp sample or the anchor is dropped (cheap sanity check against
     LLM hallucination — an anchor that never occurs can't be mined anyway).
  2. Single pass over the IndicCorp sample builds sentence-level token sets,
     document frequency, and (in a second single pass over the cached
     tokenized sentences, not a re-scan of the file, and not one pass PER
     anchor) per-anchor co-occurrence counts. PMI is computed per
     (anchor, neighbor) pair; top-8 neighbors per anchor by PMI are kept.
  3. Neighbors are transliterated Devanagari->romanized via the existing
     Devanagari->romanized dict (raw/translit_dict_hi.json) or, on a miss, a
     batched LLM call. A calibration pass compares dict vs LLM output on the
     subset where both are available and reports the agreement rate honestly.
  4. Fuzzy-snap: romanized forms that are a near-duplicate (per payload.py's
     existing Levenshtein/morphological-variant logic) of an EXISTING
     vocab/hinglish.txt spelling are snapped to that canonical spelling, so
     this module never introduces a near-duplicate spelling alongside one
     that's already in the game (e.g. "zinagi" next to "zindagi"). Only
     vocab/hinglish.txt is used as the canonical set (NOT vocab/en.txt): the
     ~55k top-English-word list would risk nonsensical cross-language snaps
     under an edit-distance threshold designed for Hindi romanization
     variants, and the spec's own example ("zinagi"->"zindagi") is squarely
     about the hinglish.txt canonical spelling list.
  5. PMI -> score: min-max normalized WITHIN this batch, then mapped to
     [0.45, 0.80] — a distinct range from assemble_data.py's fixed tier
     scores (near=0.85, mid=0.55) because this is corpus-derived relatedness,
     not hand-labeled synonymy, and should not be conflated with either tier.
     Held-out exclusion is re-run as a hard assertion (not just a filter) on
     the final records, mirroring assemble_data.py's _assert_no_leakage.
     HOMOGRAPH_COLLISIONS (assemble_data.py) is imported and applied, not
     redefined.

Run: uv run python -m evals.finetune.pmi_mine
Output: evals/finetune/data/raw/corpus_pmi_pairs.jsonl (gitignored, staging
only — see module docstring above).
"""

import json
import logging
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

from evals.finetune.assemble_data import HOMOGRAPH_COLLISIONS
from evals.finetune.llm_augment import LLMUnavailableError, _call_ollama
from evals.finetune.split import load_split
from normalize import normalize
from payload import _is_morphological_variant, levenshtein
from vocab import parse_hinglish_file

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
RAW_DIR = DATA_DIR / "raw"
AKSHARANTAR_PATH = RAW_DIR / "aksharantar_hi.jsonl"
INDICCORP_PATH = RAW_DIR / "indiccorp_v2_hi_sample.txt"
TRANSLIT_DICT_PATH = RAW_DIR / "translit_dict_hi.json"
OUT_PATH = RAW_DIR / "corpus_pmi_pairs.jsonl"

EXPECTED_N = 209_168  # sanity check: fetch_corpus_data.py's deterministic byte-prefix sample size

# Devanagari Unicode block (U+0900-U+097F). Tokenization keeps only characters
# in this range per token, discarding everything else (ASCII/Hindi punctuation,
# ZWJ/ZWNJ noise) — matches the module docstring's "strip Hindi/ASCII
# punctuation (keep Devanagari word characters)" rule. A second pass strips
# the Devanagari-block characters that are themselves punctuation/digits, not
# word characters: danda "।" / double danda "॥" (sentence-final stops),
# Devanagari digits ०-९, and the abbreviation sign "॰" — these fall INSIDE
# U+0900-U+097F so the first regex alone would keep them attached to tokens.
_NON_DEVANAGARI_RE = re.compile(r"[^ऀ-ॿ]")
_DEVANAGARI_PUNCT_DIGIT_RE = re.compile(r"[।॥०-९॰]")

MIN_COOC = 5
MIN_NEIGHBOR_DOC_FREQ = 10
MAX_NEIGHBOR_DOC_FREQ_FRAC = 0.3
TOP_K_NEIGHBORS = 8

CORPUS_OCCURRENCE_GATE_MIN = 3  # spec step 1c: anchor must occur >=3 times or be dropped

SCORE_LO = 0.45
SCORE_HI = 0.80

LLM_BATCH_SIZE = 25

SEED = 42

_DEVANAGARI_BATCH_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"word": {"type": "string"}, "devanagari": {"type": "string"}},
        "required": ["word", "devanagari"],
    },
}

_ROMANIZED_BATCH_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"devanagari": {"type": "string"}, "romanized": {"type": "string"}},
        "required": ["devanagari", "romanized"],
    },
}

_DEVANAGARI_PROMPT = """For each of the following romanized Hindi/Hinglish words, give its \
standard Devanagari spelling (the spelling a fluent Hindi reader/writer would use). Words: \
{words}.

Respond with ONLY a JSON array, no other text, no markdown fences:
[{{"word": "...", "devanagari": "..."}}, ...]"""

_ROMANIZE_PROMPT = """For each of the following Devanagari Hindi words, give its romanized \
Hinglish spelling as used in casual Hindi-English texting (lowercase, no diacritics — e.g. \
दोस्त -> dost, ज़िंदगी -> zindagi, बारिश -> baarish). Words: {words}.

Respond with ONLY a JSON array, no other text, no markdown fences:
[{{"devanagari": "...", "romanized": "..."}}, ...]"""


# ---------------------------------------------------------------------------
# Pure logic (unit-testable without corpus file / Ollama / network)
# ---------------------------------------------------------------------------


def tokenize(sentence: str) -> list[str]:
    """
    Split `sentence` on whitespace, strip everything except Devanagari word
    characters from each token, lowercase (a no-op for Devanagari, applied
    for consistency), and drop tokens that become empty.
    """
    tokens: list[str] = []
    for raw in sentence.split():
        cleaned = _NON_DEVANAGARI_RE.sub("", raw)
        cleaned = _DEVANAGARI_PUNCT_DIGIT_RE.sub("", cleaned).lower()
        if cleaned:
            tokens.append(cleaned)
    return tokens


def compute_pmi(cooc_count: int, anchor_doc_freq: int, neighbor_doc_freq: int, n: int) -> float:
    """
    Pointwise mutual information between anchor and neighbor, computed from
    sentence-level document frequencies (see module docstring step 2):

        PMI = log2( P(anchor, neighbor) / (P(anchor) * P(neighbor)) )
            = log2( (cooc_count / n) / ((anchor_doc_freq / n) * (neighbor_doc_freq / n)) )

    Raises ZeroDivisionError/ValueError naturally if inputs are degenerate
    (n=0, either doc_freq=0, or cooc_count=0 -> log2(0)) — callers are
    expected to only call this after the doc-freq/cooc-count filters in
    select_neighbors have already excluded degenerate inputs.
    """
    p_xy = cooc_count / n
    p_x = anchor_doc_freq / n
    p_y = neighbor_doc_freq / n
    return math.log2(p_xy / (p_x * p_y))


def select_neighbors(
    anchor_devanagari: str,
    cooc_counts: Counter[str],
    doc_freq: Counter[str],
    n: int,
) -> list[dict]:
    """
    Filter and rank an anchor's co-occurring tokens per spec step 2:
      - cooc_count >= MIN_COOC
      - MIN_NEIGHBOR_DOC_FREQ <= neighbor_doc_freq <= n * MAX_NEIGHBOR_DOC_FREQ_FRAC
        (the upper cap filters function words/postpositions like का/के/में/है
        without a hand-maintained stopword list)
      - PMI > 0 (genuinely more associated than chance)
    Returns the top TOP_K_NEIGHBORS by PMI descending (ties broken
    alphabetically by neighbor spelling, for determinism).
    """
    anchor_doc_freq = doc_freq[anchor_devanagari]
    max_neighbor_freq = n * MAX_NEIGHBOR_DOC_FREQ_FRAC
    candidates: list[dict] = []
    for neighbor, cooc_count in cooc_counts.items():
        if cooc_count < MIN_COOC:
            continue
        neighbor_doc_freq = doc_freq[neighbor]
        if neighbor_doc_freq < MIN_NEIGHBOR_DOC_FREQ or neighbor_doc_freq > max_neighbor_freq:
            continue
        if anchor_doc_freq == 0 or neighbor_doc_freq == 0:
            continue
        pmi = compute_pmi(cooc_count, anchor_doc_freq, neighbor_doc_freq, n)
        if pmi <= 0:
            continue
        candidates.append(
            {
                "neighbor_devanagari": neighbor,
                "cooc_count": cooc_count,
                "neighbor_doc_freq": neighbor_doc_freq,
                "pmi": pmi,
            }
        )
    candidates.sort(key=lambda c: (-c["pmi"], c["neighbor_devanagari"]))
    return candidates[:TOP_K_NEIGHBORS]


def pmi_to_score(
    pmi: float, pmi_min: float, pmi_max: float, lo: float = SCORE_LO, hi: float = SCORE_HI
) -> float:
    """
    Min-max normalize `pmi` within [pmi_min, pmi_max] then map to [lo, hi].

    If pmi_min == pmi_max (degenerate single-value batch), returns the
    midpoint (lo + hi) / 2 rather than dividing by zero.
    """
    if pmi_max == pmi_min:
        return (lo + hi) / 2
    normalized = (pmi - pmi_min) / (pmi_max - pmi_min)
    return lo + normalized * (hi - lo)


def fuzzy_snap(word: str, canonical_vocab: frozenset[str]) -> tuple[str, bool]:
    """
    Snap `word` to an existing canonical spelling in `canonical_vocab` if
    payload.py's morphological-variant check considers them near-duplicates
    (reuses _is_morphological_variant/levenshtein — not redefined here).

    Returns (final_word, was_snapped):
      - if `word` is already in canonical_vocab, returns (word, False) —
        nothing to snap, it's already canonical.
      - if `word` fuzzy-matches one or more canonical entries, snaps to the
        one with the lowest Levenshtein distance (ties broken alphabetically,
        for determinism).
      - otherwise returns (word, False) unchanged.
    """
    if word in canonical_vocab:
        return word, False
    matches = [c for c in canonical_vocab if _is_morphological_variant(word, c)]
    if not matches:
        return word, False
    best = min(matches, key=lambda c: (levenshtein(word, c), c))
    return best, True


def build_romanized_to_devanagari_counts(
    pairs: list[tuple[str, str]],
) -> dict[str, Counter[str]]:
    """
    Pure aggregation step of build_romanized_to_devanagari: tally, for every
    lowercased romanized form, a Counter of the Devanagari spellings paired
    with it in `pairs` (weighted by occurrence count in the raw data). Split
    out from the JSONL-reading I/O so it's unit-testable on a small in-memory
    list.
    """
    tally: dict[str, Counter[str]] = defaultdict(Counter)
    for deva, rom in pairs:
        tally[rom.strip().lower()][deva] += 1
    return tally


def pick_best_devanagari(counts: Counter[str]) -> str:
    """
    Tie-break policy (mirrors fetch_corpus_data.build_translit_dict): highest
    pair-frequency wins; ties broken by (1) shortest string, then (2)
    alphabetically first. Deterministic, no seed needed.
    """
    best, _ = min(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
    return best


def compute_calibration(
    dict_hit_devas: list[str],
    dict_rom: dict[str, str],
    llm_rom: dict[str, str],
) -> dict:
    """
    Compare dict-derived vs LLM-derived romanization for the subset of
    neighbors where the dict DOES have a hit (spec step 3 calibration check).
    Exact match is checked after normalize()'s vowel-length/spelling folding
    (project's existing fold, not a fresh fuzzy-match threshold). Reports the
    agreement rate honestly, including when it's poor.
    """
    rows: list[dict] = []
    agree = 0
    compared = 0
    for deva in dict_hit_devas:
        d_rom = dict_rom.get(deva)
        l_rom = llm_rom.get(deva)
        if d_rom is None or l_rom is None:
            continue
        compared += 1
        match = normalize(d_rom) == normalize(l_rom)
        if match:
            agree += 1
        rows.append({"devanagari": deva, "dict": d_rom, "llm": l_rom, "match": match})
    return {
        "n_compared": compared,
        "n_agree": agree,
        "agreement_rate": (agree / compared) if compared else None,
        "rows": rows,
    }


def candidate_anchors(held_out: set[str]) -> list[str]:
    """
    vocab/hinglish.txt romanized words minus held-out secrets/translations
    (case-insensitive), deduplicated preserving file order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for word, _anchor in parse_hinglish_file():
        if word in held_out or word in seen:
            continue
        seen.add(word)
        result.append(word)
    return result


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ---------------------------------------------------------------------------
# I/O: corpus loading, Aksharantar pairs, Ollama calls
# ---------------------------------------------------------------------------


def load_corpus(path: Path) -> tuple[list[frozenset[str]], Counter[str], Counter[str]]:
    """
    Single pass over `path` (one sentence per line): tokenize each sentence,
    accumulate a raw term-frequency Counter (all occurrences, used for the
    step-1c anchor corpus-occurrence gate: "appears as a token >=3 times") and
    a sentence-level document-frequency Counter (used for PMI), and cache each
    sentence's deduplicated token set for reuse in the co-occurrence mining
    pass (mine_cooccurrences) — so that pass is a second loop over this
    already-tokenized, in-memory structure, not a re-scan of the raw file.
    """
    sentence_sets: list[frozenset[str]] = []
    term_freq: Counter[str] = Counter()
    doc_freq: Counter[str] = Counter()
    with path.open(encoding="utf-8") as f:
        for line in f:
            tokens = tokenize(line)
            if not tokens:
                sentence_sets.append(frozenset())
                continue
            term_freq.update(tokens)
            token_set = frozenset(tokens)
            doc_freq.update(token_set)
            sentence_sets.append(token_set)
    return sentence_sets, term_freq, doc_freq


def mine_cooccurrences(
    anchor_devas: set[str], sentence_sets: list[frozenset[str]]
) -> dict[str, Counter[str]]:
    """
    Single pass over the cached tokenized sentences (spec step 2: "don't
    re-scan per anchor — build corpus-wide structures once"): for every
    sentence, find which anchors are present and credit every OTHER token in
    that sentence's (deduplicated) token set to that anchor's co-occurrence
    Counter. One pass handles all anchors simultaneously.
    """
    cooc: dict[str, Counter[str]] = {d: Counter() for d in anchor_devas}
    for tokens in sentence_sets:
        present = tokens & anchor_devas
        if not present:
            continue
        for anchor in present:
            cooc[anchor].update(tokens - {anchor})
    return cooc


def load_aksharantar_pairs(path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            pairs.append((rec["devanagari"], rec["romanized"]))
    return pairs


def build_romanized_to_devanagari(path: Path) -> dict[str, str]:
    """
    {romanized_lowercased: devanagari} built from Aksharantar's RAW pairs
    (not the already-deduped Devanagari->romanized dict, which is the wrong
    direction and the wrong aggregation for this lookup). See
    build_romanized_to_devanagari_counts/pick_best_devanagari for the pure
    tie-break logic.
    """
    pairs = load_aksharantar_pairs(path)
    tally = build_romanized_to_devanagari_counts(pairs)
    return {rom: pick_best_devanagari(counts) for rom, counts in tally.items()}


def llm_devanagari_batch(words: list[str]) -> dict[str, str]:
    """One batched Ollama call: {romanized_lowercased: devanagari} for as many
    of `words` as the model answered (batched, not one call per word, to keep
    runtime tractable — see module docstring; still $0/local, same qwen3:8b
    model as llm_augment.py/homograph_audit.py)."""
    prompt = _DEVANAGARI_PROMPT.format(words=", ".join(words))
    try:
        raw = _call_ollama(prompt, response_format=_DEVANAGARI_BATCH_SCHEMA)
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("devanagari batch failed for %d words: %s", len(words), e)
        return {}
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for rec in raw:
        if (
            isinstance(rec, dict)
            and isinstance(rec.get("word"), str)
            and isinstance(rec.get("devanagari"), str)
            and rec["devanagari"].strip()
        ):
            out[rec["word"].strip().lower()] = rec["devanagari"].strip()
    return out


def llm_romanize_batch(deva_words: list[str]) -> dict[str, str]:
    """One batched Ollama call: {devanagari: romanized_lowercased}."""
    prompt = _ROMANIZE_PROMPT.format(words=", ".join(deva_words))
    try:
        raw = _call_ollama(prompt, response_format=_ROMANIZED_BATCH_SCHEMA)
    except (LLMUnavailableError, json.JSONDecodeError) as e:
        logger.warning("romanize batch failed for %d words: %s", len(deva_words), e)
        return {}
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for rec in raw:
        if (
            isinstance(rec, dict)
            and isinstance(rec.get("devanagari"), str)
            and isinstance(rec.get("romanized"), str)
            and rec["romanized"].strip()
        ):
            out[rec["devanagari"].strip()] = rec["romanized"].strip().lower()
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _held_out(split: dict) -> set[str]:
    return {w.lower() for w in split["held_out_secrets"]} | {
        w.lower() for w in split["held_out_en_translations"]
    }


def resolve_anchors(
    candidates: list[str], rom_to_deva: dict[str, str], term_freq: Counter[str]
) -> tuple[list[dict], dict]:
    """
    Spec step 1: for each candidate, resolve Devanagari via dict (primary) or
    a batched LLM fallback for dict misses, then apply the corpus-occurrence
    gate (>= CORPUS_OCCURRENCE_GATE_MIN token occurrences in the IndicCorp
    sample). Returns (accepted_anchor_records, stats). Anchors whose dict/LLM
    resolution produced nothing are NOT retried via the other method (dict
    miss -> LLM only; LLM non-answer -> dropped) — documented simplification,
    the corpus gate is the safety net either way.
    """
    dict_hits = [w for w in candidates if w in rom_to_deva]
    needs_llm = [w for w in candidates if w not in rom_to_deva]

    llm_results: dict[str, str] = {}
    for chunk in _chunks(needs_llm, LLM_BATCH_SIZE):
        llm_results.update(llm_devanagari_batch(chunk))

    accepted: list[dict] = []
    dropped_llm_no_answer = 0
    dropped_corpus_not_found = 0
    dropped_corpus_low_freq = 0

    for w in candidates:
        if w in rom_to_deva:
            deva = rom_to_deva[w]
            source = "dict"
        else:
            deva = llm_results.get(w)
            source = "llm"
        if not deva:
            dropped_llm_no_answer += 1
            continue
        freq = term_freq.get(deva, 0)
        if freq == 0:
            dropped_corpus_not_found += 1
            continue
        if freq < CORPUS_OCCURRENCE_GATE_MIN:
            dropped_corpus_low_freq += 1
            continue
        accepted.append({"word": w, "devanagari": deva, "source": source})

    stats = {
        "candidates_considered": len(candidates),
        "resolved_via_dict": len(dict_hits),
        "llm_fallback_attempted": len(needs_llm),
        "llm_fallback_succeeded": sum(1 for a in accepted if a["source"] == "llm"),
        "dropped_llm_no_answer": dropped_llm_no_answer,
        "dropped_corpus_not_found": dropped_corpus_not_found,
        "dropped_corpus_low_freq_lt_3": dropped_corpus_low_freq,
        "final_anchor_count": len(accepted),
    }
    return accepted, stats


def _assert_no_leakage(records: list[dict], held_out: set[str]) -> None:
    for r in records:
        assert r["anchor"].lower() not in held_out, f"LEAKAGE in corpus_pmi_pairs: {r}"
        assert r["neighbor"].lower() not in held_out, f"LEAKAGE in corpus_pmi_pairs: {r}"


def build() -> dict:
    split = load_split()
    held_out = _held_out(split)

    print(f"Loading IndicCorp sample from {INDICCORP_PATH} ...")
    sentence_sets, term_freq, doc_freq = load_corpus(INDICCORP_PATH)
    n = len(sentence_sets)
    if n != EXPECTED_N:
        raise ValueError(f"corpus sentence count changed: got {n}, expected {EXPECTED_N}")
    print(f"  {n:,} sentences, {len(doc_freq):,} unique tokens")

    print("Building romanized->devanagari dict from Aksharantar raw pairs ...")
    rom_to_deva = build_romanized_to_devanagari(AKSHARANTAR_PATH)
    print(f"  {len(rom_to_deva):,} unique romanized forms")

    print("Resolving candidate anchors ...")
    candidates = candidate_anchors(held_out)
    anchors, anchor_stats = resolve_anchors(candidates, rom_to_deva, term_freq)
    print(f"  {json.dumps(anchor_stats)}")

    print("Mining PMI co-occurrences ...")
    anchor_devas = {a["devanagari"] for a in anchors}
    cooc = mine_cooccurrences(anchor_devas, sentence_sets)

    mined: list[dict] = []
    for a in anchors:
        neighbors = select_neighbors(a["devanagari"], cooc[a["devanagari"]], doc_freq, n)
        for nb in neighbors:
            mined.append(
                {
                    "anchor_word": a["word"],
                    "anchor_devanagari": a["devanagari"],
                    "anchor_source": a["source"],
                    "neighbor_devanagari": nb["neighbor_devanagari"],
                    "cooc_count": nb["cooc_count"],
                    "pmi": nb["pmi"],
                }
            )
    print(f"  {len(mined):,} raw (anchor, neighbor) pairs mined")

    print("Transliterating neighbors (dict primary, batched LLM fallback) ...")
    deva_to_rom: dict[str, str] = json.loads(TRANSLIT_DICT_PATH.read_text(encoding="utf-8"))
    unique_neighbor_devas = sorted({m["neighbor_devanagari"] for m in mined})
    dict_hit_devas = [d for d in unique_neighbor_devas if d in deva_to_rom]
    needs_llm_devas = [d for d in unique_neighbor_devas if d not in deva_to_rom]

    llm_rom_results: dict[str, str] = {}
    for chunk in _chunks(needs_llm_devas, LLM_BATCH_SIZE):
        llm_rom_results.update(llm_romanize_batch(chunk))

    print("Calibration: dict vs LLM romanization on dict-hit neighbors ...")
    calibration_llm_results: dict[str, str] = {}
    for chunk in _chunks(dict_hit_devas, LLM_BATCH_SIZE):
        calibration_llm_results.update(llm_romanize_batch(chunk))
    calibration = compute_calibration(dict_hit_devas, deva_to_rom, calibration_llm_results)
    print(
        f"  calibration: {calibration['n_agree']}/{calibration['n_compared']} agree "
        f"(rate={calibration['agreement_rate']})"
    )

    neighbor_rom: dict[str, tuple[str, str]] = {}
    for d in dict_hit_devas:
        neighbor_rom[d] = (deva_to_rom[d].strip().lower(), "dict")
    for d in needs_llm_devas:
        rom = llm_rom_results.get(d)
        if rom:
            neighbor_rom[d] = (rom.strip().lower(), "llm")

    transliterated: list[dict] = []
    dropped_no_translit = 0
    dropped_held_out_neighbor = 0
    for m in mined:
        rom_info = neighbor_rom.get(m["neighbor_devanagari"])
        if rom_info is None:
            dropped_no_translit += 1
            continue
        neighbor_word, neighbor_source = rom_info
        if not neighbor_word or not neighbor_word.isalpha():
            dropped_no_translit += 1
            continue
        if neighbor_word in held_out:
            dropped_held_out_neighbor += 1
            continue
        transliterated.append(
            {**m, "neighbor_word": neighbor_word, "neighbor_source": neighbor_source}
        )
    print(
        f"  {len(transliterated):,} pairs after transliteration "
        f"(dropped {dropped_no_translit} no-translit, "
        f"{dropped_held_out_neighbor} held-out-neighbor)"
    )

    print("Fuzzy-snapping to canonical vocab/hinglish.txt spellings ...")
    # canonical set excludes held-out words so snapping can never reintroduce
    # a held-out spelling under a different surface form.
    canonical_vocab = frozenset(w for w, _ in parse_hinglish_file() if w not in held_out)
    snapped: list[dict] = []
    n_anchor_snapped = 0
    n_neighbor_snapped = 0
    for r in transliterated:
        anchor_final, a_snapped = fuzzy_snap(r["anchor_word"], canonical_vocab)
        neighbor_final, n_snapped = fuzzy_snap(r["neighbor_word"], canonical_vocab)
        if a_snapped:
            n_anchor_snapped += 1
        if n_snapped:
            n_neighbor_snapped += 1
        snapped.append(
            {
                **r,
                "anchor_final": anchor_final,
                "neighbor_final": neighbor_final,
                "anchor_snapped": a_snapped,
                "neighbor_snapped": n_snapped,
            }
        )
    print(f"  snapped: anchor={n_anchor_snapped}, neighbor={n_neighbor_snapped}")

    print("Scoring + final exclusions ...")
    pmi_values = [r["pmi"] for r in snapped]
    pmi_min = min(pmi_values) if pmi_values else 0.0
    pmi_max = max(pmi_values) if pmi_values else 0.0

    final_records: list[dict] = []
    dropped_self_pair = 0
    dropped_homograph = 0
    for r in snapped:
        anchor_f = r["anchor_final"]
        neighbor_f = r["neighbor_final"]
        if anchor_f == neighbor_f:
            dropped_self_pair += 1
            continue
        if anchor_f in HOMOGRAPH_COLLISIONS or neighbor_f in HOMOGRAPH_COLLISIONS:
            dropped_homograph += 1
            continue
        score = pmi_to_score(r["pmi"], pmi_min, pmi_max)
        final_records.append(
            {
                "anchor": anchor_f,
                "neighbor": neighbor_f,
                "pmi": r["pmi"],
                "cooccurrence_count": r["cooc_count"],
                "score": score,
                "anchor_translit_source": r["anchor_source"],
                "neighbor_translit_source": r["neighbor_source"],
                "snapped_anchor": r["anchor_snapped"],
                "snapped_neighbor": r["neighbor_snapped"],
            }
        )

    seen_pairs: set[tuple[str, str]] = set()
    deduped_final: list[dict] = []
    n_dedup_dropped = 0
    for r in final_records:
        key = (r["anchor"], r["neighbor"])
        if key in seen_pairs:
            n_dedup_dropped += 1
            continue
        seen_pairs.add(key)
        deduped_final.append(r)

    _assert_no_leakage(deduped_final, held_out)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in deduped_final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    stats = {
        "corpus_sentences": n,
        "anchor_resolution": anchor_stats,
        "raw_mined_pairs": len(mined),
        "after_transliteration": len(transliterated),
        "dropped_no_translit": dropped_no_translit,
        "dropped_held_out_neighbor": dropped_held_out_neighbor,
        "snapped_anchor_count": n_anchor_snapped,
        "snapped_neighbor_count": n_neighbor_snapped,
        "dropped_self_pair": dropped_self_pair,
        "dropped_homograph": dropped_homograph,
        "dropped_exact_dup": n_dedup_dropped,
        "final_pair_count": len(deduped_final),
        "translit_calibration": calibration,
        "output_path": str(OUT_PATH),
    }
    return stats


if __name__ == "__main__":
    result = build()
    print(json.dumps({k: v for k, v in result.items() if k != "translit_calibration"}, indent=2))
    print(
        "calibration agreement_rate:",
        result["translit_calibration"]["agreement_rate"],
        f"({result['translit_calibration']['n_agree']}/{result['translit_calibration']['n_compared']})",
    )
