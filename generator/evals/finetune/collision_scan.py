from __future__ import annotations

"""
Systematic subword-tokenization-collision scan across the FULL ~10,495-word
hi-en vocab (spec-model-excellence.md WORKSTREAM B, item 8).

Background (the only prior art -- probe_subword_collision.py): 9 candidate
words were found by MANUALLY inspecting each word's top-15 nearest
neighbors under the shipped model's hi-en embedding, looking for the
"junoon/registan" signature -- correct gloss ranks poorly, and the top
neighbors are dominated by unrelated English words sharing a coincidental
subword fragment rather than genuine synonyms/associates (e.g.
junoon->afternoon/noon/june, registan->register/registry/registration; see
public_benchmark_phase1_report.md's v1.1 addendum for the two words the
report itself calls the CLEAR cases -- jheel/udaasi are explicitly flagged
there as only "partially" exhibiting the signature). That manual process
does not scale to 544 hinglish-sourced words, so this module turns the
signature into a programmatic score and runs it across all of them.

Only HINGLISH-SOURCED words (~544, from vocab/hinglish.txt) are scanned as
collision CANDIDATES -- the failure mode this scan targets is specifically
a romanized-Hindi word being confused with orthographically-similar ENGLISH
vocab entries, not the reverse. English-sourced words are only ever
inspected in the role of "possible colliding neighbor," never as a scan
subject (see `hien_word_origin`).

Run (from generator/):
    uv run python -m evals.finetune.collision_scan
"""

import json
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from config import MODELS
from embeddings import cosine_similarities, embed_vocab
from payload import levenshtein
from profanity import load_en_profanity, load_hi_profanity
from vocab import load_devanagari_patch, load_hien_vocab, parse_hinglish_file

DATA_DIR = Path(__file__).parent / "data"

K_NEIGHBORS = 15  # matches the prior manual-inspection K (probe_subword_collision.py)

# Collision-prone threshold: a hinglish word is flagged if its top-15
# neighbors are >= this fraction english-sourced-and-orthographically-similar.
# Chosen against the calibration table (see `run_calibration`, numbers
# recorded in collision_scan_report.md): at 0.2 (3/15), 11 of the 13
# calibration words clear the bar -- BOTH words the source report
# (public_benchmark_phase1_report.md v1.1 addendum) explicitly calls CLEAR
# collision cases (junoon 0.467, registan 0.400), plus jheel (0.333) and 7
# of the other 8 probe_subword_collision.py candidates (daraa, accha,
# angocha, sharbat, seedha, seena, halwa, chashma all >= 0.2). The 2
# misses -- naukri (0.000) and udaasi (0.000) -- are a documented, honest
# limitation, not a tuning failure: naukri's historical hard-negative
# ("norfolk") and udaasi's collision signature share ZERO surface-character
# overlap with the anchor word (verified: naukri/norfolk have no common
# bigram at all), i.e. they are pure embedding-space/subword-token
# artifacts no character-level heuristic can catch -- see
# `orthographically_similar`'s docstring. udaasi is also the report's own
# "partially" (not clearly) confirmed case, so a lower score here is
# consistent with the source evidence, not a red flag. Raising the
# threshold further to try to catch these 2 would not help (they score
# exactly 0, not "just under") and would only shrink true-positive
# coverage elsewhere; lowering it below 0.2 was tried and produced 306/544
# (56%) flagged, clearly too loose to be a "collision-prone" signal (see
# PR/report discussion).
COLLISION_THRESHOLD = 0.2


# ---------------------------------------------------------------------------
# Part 1.1 -- hi-en vocab origin (hinglish.txt vs en.txt), reconstructed by
# mirroring vocab.load_hien_vocab()'s exact filter+dedup logic.
# ---------------------------------------------------------------------------


def hinglish_sourced_words() -> frozenset[str]:
    """The set of vocab words sourced from vocab/hinglish.txt, exactly as
    vocab.load_hien_vocab() computes its `hi_words` list (profanity-filtered,
    first-occurrence-deduplicated) -- mirrored here read-only, vocab.py is
    never modified or reimported private internals of."""
    profanity = load_en_profanity() | load_hi_profanity()
    seen: set[str] = set()
    words: list[str] = []
    for w, _anchor in parse_hinglish_file():
        if w not in profanity and w not in seen:
            words.append(w)
            seen.add(w)
    return frozenset(words)


def hinglish_anchor_glosses() -> dict[str, str]:
    """word -> English anchor gloss from hinglish.txt, first occurrence wins
    (same precedence vocab.load_hien_vocab() applies for dedup)."""
    out: dict[str, str] = {}
    for w, anchor in parse_hinglish_file():
        if w not in out:
            out[w] = anchor
    return out


def hien_word_origin(vocab: list[str]) -> dict[str, str]:
    """Map every word in `vocab` to `"hinglish"` (sourced from hinglish.txt)
    or `"english"` (sourced from en.txt's top-N via load_hien_vocab's
    English top-up). Pure membership check -- independent of `vocab`'s
    order."""
    hi_words = hinglish_sourced_words()
    return {w: ("hinglish" if w in hi_words else "english") for w in vocab}


# ---------------------------------------------------------------------------
# Part 1.2 -- nearest-neighbor + orthographic-similarity primitives.
# ---------------------------------------------------------------------------


def top_k_neighbors(matrix: NDArray[np.float32], idx: int, k: int) -> list[int]:
    """Indices of the top-k nearest neighbors (cosine similarity) to
    matrix[idx], excluding idx itself. Same cosine-sim + argsort(-sims)
    pattern as evals.harness.dimension1_ranking._resolve_actuals (lines
    63-69), factored into a reusable function since none currently exists.
    """
    sims = cosine_similarities(matrix, matrix[idx])
    order = np.argsort(-sims)
    neighbors = [int(i) for i in order if int(i) != idx]
    return neighbors[:k]


def _shares_contiguous_run(a: str, b: str, min_len: int) -> bool:
    """True iff `a` and `b` share a contiguous substring of length
    >= min_len, anywhere in either string (prefix, suffix, or interior)."""
    if min_len > len(a):
        return False
    return any(a[i : i + min_len] in b for i in range(len(a) - min_len + 1))


def orthographically_similar(a: str, b: str) -> bool:
    """
    True iff `a` and `b` are similar enough at the character level to
    plausibly explain a subword-tokenization collision (as opposed to a
    coincidental one-letter overlap or a genuinely unrelated word pair).

    Formula (either condition suffices):
      1. normalized Levenshtein distance <= 0.6, where
         normalized = levenshtein(a, b) / max(len(a), len(b))
         (catches near-misspellings/short edit-distance pairs, e.g.
         seedha/seed, registan/register).
      2. `a` and `b` share a contiguous substring (prefix, suffix, or
         interior) of length >= 3 -- or length >= 2 when the SHORTER of the
         two strings has length <= 4 (short words need a shorter shared run
         to register meaningfully at all, e.g. accha/ac, accha/ace).

    This intentionally does NOT catch every subword-tokenizer collision --
    some (e.g. naukri/norfolk from the prior manual probe) are pure
    embedding-space/subword-token artifacts with zero surface-string overlap
    and are undetectable by any character-level heuristic. `collision_score`
    below only needs ONE qualifying neighbor among a word's top-15 to
    contribute, so a formula that catches most-but-not-all collision
    fragments still produces a usable score -- see the calibration table for
    the honest empirical result, including cases where this known limitation
    shows up.
    """
    normalized = levenshtein(a, b) / max(len(a), len(b))
    if normalized <= 0.6:
        return True
    shorter = min(len(a), len(b))
    min_len = 2 if shorter <= 4 else 3
    return _shares_contiguous_run(a, b, min_len)


# ---------------------------------------------------------------------------
# Part 1.3 -- collision score.
# ---------------------------------------------------------------------------


def analyze_word(
    word: str,
    idx: int,
    matrix: NDArray[np.float32],
    vocab: list[str],
    origin: dict[str, str],
    glosses: dict[str, str],
    k: int = K_NEIGHBORS,
) -> dict:
    """Full collision analysis for one hinglish-sourced word: its top-k
    neighbors (each tagged with origin + orthographic-similarity to `word`),
    and collision_score = (# neighbors that are BOTH english-sourced AND
    orthographically similar to `word`) / k.
    """
    neighbor_idxs = top_k_neighbors(matrix, idx, k)
    neighbor_detail = []
    n_colliding = 0
    for n_idx in neighbor_idxs:
        n_word = vocab[n_idx]
        n_origin = origin[n_word]
        is_collision = n_origin == "english" and orthographically_similar(word, n_word)
        if is_collision:
            n_colliding += 1
        neighbor_detail.append(
            {"word": n_word, "origin": n_origin, "orthographically_similar": is_collision}
        )
    return {
        "word": word,
        "gloss": glosses.get(word),
        "collision_score": n_colliding / k,
        "n_colliding_neighbors": n_colliding,
        "k": k,
        "neighbors": neighbor_detail,
    }


# ---------------------------------------------------------------------------
# Part 1.4 -- calibration against known-positive collision words.
# ---------------------------------------------------------------------------


def known_positive_words() -> list[str]:
    """The 9 hand-picked words from probe_subword_collision.py's
    PROBE_CANDIDATES + the 4 words already shipped in the live L2 patch
    (junoon/registan/jheel/udaasi -- definitely real collisions since they
    are already production fixes). Read-only import/lookup, no
    duplication of the underlying lists."""
    from evals.finetune.probe_subword_collision import PROBE_CANDIDATES

    probe_words = [c["word"] for c in PROBE_CANDIDATES]
    patch_words = list(load_devanagari_patch().keys())  # read-only load
    seen: set[str] = set()
    out: list[str] = []
    for w in probe_words + patch_words:
        if w not in seen:
            out.append(w)
            seen.add(w)
    return out


def run_calibration(
    matrix: NDArray[np.float32], vocab: list[str], origin: dict[str, str], glosses: dict[str, str]
) -> list[dict]:
    """Score every known-positive calibration word, in the same shape as the
    full scan's per-word results."""
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    results = []
    for w in known_positive_words():
        if w not in word_to_idx:
            results.append({"word": w, "error": "not in hi-en vocab"})
            continue
        results.append(analyze_word(w, word_to_idx[w], matrix, vocab, origin, glosses))
    return results


# ---------------------------------------------------------------------------
# Part 1.5 -- full scan across all hinglish-sourced words.
# ---------------------------------------------------------------------------


def run_full_scan(
    matrix: NDArray[np.float32], vocab: list[str], origin: dict[str, str], glosses: dict[str, str]
) -> list[dict]:
    """Score every hinglish-sourced word in `vocab`, ranked collision_score
    descending (ties broken by word, for determinism)."""
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    hi_words = [w for w in vocab if origin[w] == "hinglish"]
    results = [
        analyze_word(w, word_to_idx[w], matrix, vocab, origin, glosses) for w in hi_words
    ]
    results.sort(key=lambda r: (-r["collision_score"], r["word"]))
    return results


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------


def _fmt_neighbors(neighbors: list[dict]) -> str:
    parts = []
    for n in neighbors:
        flag = "*" if n["orthographically_similar"] else ""
        parts.append(f"{n['word']}{flag}({n['origin'][0]})")
    return ", ".join(parts)


def render_markdown(calibration: list[dict], full_scan: list[dict], threshold: float) -> str:
    lines = [
        "# Subword-collision scan report",
        "",
        f"K={K_NEIGHBORS}, threshold={threshold} "
        "(neighbor origin=english AND orthographically_similar -- see "
        "collision_scan.orthographically_similar's docstring for the exact "
        "formula). `*` marks a neighbor counted toward the score; `(e)`/`(h)` "
        "= english/hinglish origin.",
        "",
        "## Calibration (known collision words)",
        "",
        "| word | gloss | collision_score | n/K | top neighbors |",
        "|---|---|---|---|---|",
    ]
    for r in calibration:
        if "error" in r:
            lines.append(f"| {r['word']} | - | ERROR | - | {r['error']} |")
            continue
        lines.append(
            f"| {r['word']} | {r['gloss']} | {r['collision_score']:.3f} | "
            f"{r['n_colliding_neighbors']}/{r['k']} | {_fmt_neighbors(r['neighbors'])} |"
        )
    lines += [
        "",
        f"## Full scan: {len(full_scan)} hinglish-sourced words, "
        f"{sum(1 for r in full_scan if r['collision_score'] >= threshold)} >= threshold "
        f"({threshold})",
        "",
        "### Top 20 most severe",
        "",
        "| word | gloss | collision_score | n/K | top neighbors |",
        "|---|---|---|---|---|",
    ]
    for r in full_scan[:20]:
        lines.append(
            f"| {r['word']} | {r['gloss']} | {r['collision_score']:.3f} | "
            f"{r['n_colliding_neighbors']}/{r['k']} | {_fmt_neighbors(r['neighbors'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    vocab = load_hien_vocab()
    print(f"hi-en vocab size: {len(vocab)}, model: {MODELS['hi-en']}")
    matrix = embed_vocab(vocab, "hi-en")
    origin = hien_word_origin(vocab)
    glosses = hinglish_anchor_glosses()
    n_hinglish = sum(1 for v in origin.values() if v == "hinglish")
    n_english = sum(1 for v in origin.values() if v == "english")
    print(f"origin split: hinglish={n_hinglish}, english={n_english}")

    calibration = run_calibration(matrix, vocab, origin, glosses)
    print("calibration table:")
    for r in calibration:
        if "error" in r:
            print(f"  {r['word']}: {r['error']}")
        else:
            print(f"  {r['word']}: collision_score={r['collision_score']:.3f}")

    full_scan = run_full_scan(matrix, vocab, origin, glosses)
    n_flagged = sum(1 for r in full_scan if r["collision_score"] >= COLLISION_THRESHOLD)
    print(f"collision-prone (score >= {COLLISION_THRESHOLD}): {n_flagged}/{len(full_scan)}")

    report = {
        "k": K_NEIGHBORS,
        "threshold": COLLISION_THRESHOLD,
        "model": MODELS["hi-en"],
        "n_hinglish_sourced": n_hinglish,
        "n_english_sourced": n_english,
        "n_flagged": n_flagged,
        "calibration": calibration,
        "full_scan": full_scan,
    }
    out_json = DATA_DIR / "collision_scan_report.json"
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_json}")

    out_md = DATA_DIR / "collision_scan_report.md"
    out_md.write_text(
        render_markdown(calibration, full_scan, COLLISION_THRESHOLD), encoding="utf-8"
    )
    print(f"wrote {out_md}")


if __name__ == "__main__":
    main()
