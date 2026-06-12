from __future__ import annotations

"""
Vocabulary loaders for English and Hinglish (hi-en) puzzle modes.

English vocab:
  - Derived from wordfreq.top_n_list("en", 80000)
  - Filters: single whitespace token, alpha-only ASCII, length 3-15, not profane
  - Cached to vocab/en.txt for reproducible builds (re-derive if file absent)

Hinglish vocab:
  - Base: curated hinglish.txt (word<TAB>anchor pairs)
  - Combined with top ~10k filtered English words (code-mixed play; players type both)
  - All embedded with the multilingual model
"""

import re
from pathlib import Path

from config import EN_MAX_LEN, EN_MIN_LEN, EN_TOP_N, EN_VOCAB_MAX, HIEN_EN_TOP_N, VOCAB_DIR
from profanity import load_en_profanity, load_hi_profanity

_ASCII_ALPHA_RE = re.compile(r"^[a-z]+$")


def _is_valid_en_word(word: str, profanity: frozenset[str]) -> bool:
    """
    Return True iff the word passes all English vocab filters.

    Filters are ordered cheapest-first:
    1. Length bound (avoids regex on clearly invalid tokens).
    2. ASCII alpha-only (no digits, hyphens, apostrophes).
    3. Profanity check.
    """
    w = word.lower()
    if not (EN_MIN_LEN <= len(w) <= EN_MAX_LEN):
        return False
    if not _ASCII_ALPHA_RE.match(w):
        return False
    return w not in profanity


def derive_en_vocab() -> list[str]:
    """
    Derive English vocabulary from wordfreq, apply filters, return frequency-ordered list.

    wordfreq.top_n_list returns words roughly in frequency order (most common first).
    We preserve that ordering in the output list — do NOT sort alphabetically,
    because downstream callers may depend on index stability.
    The result is capped at EN_VOCAB_MAX to comply with the spec range of ~40–60k words.
    """
    from wordfreq import top_n_list  # local import so test stubs can avoid it

    profanity = load_en_profanity()
    raw = top_n_list("en", EN_TOP_N)
    filtered = [w.lower() for w in raw if _is_valid_en_word(w, profanity)]
    # Cap to spec range — wordfreq order is frequency order, so truncation keeps the most common.
    return filtered[:EN_VOCAB_MAX]


def load_en_vocab() -> list[str]:
    """
    Return English vocab list: read from vocab/en.txt if present, else derive and cache.

    The file cache ensures vocab stability across wordfreq version bumps.
    Words in en.txt that fail current filters are silently skipped on reload —
    this lets us tighten filters without re-deriving, at the cost of minor drift.
    """
    cache_path = VOCAB_DIR / "en.txt"
    if cache_path.exists():
        profanity = load_en_profanity()
        words: list[str] = []
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            w = line.strip()
            if w and not w.startswith("#"):
                wl = w.lower()
                if _is_valid_en_word(wl, profanity):
                    words.append(wl)
                    # Cap enforced here too so a stale oversized en.txt can't leak through.
                    if len(words) >= EN_VOCAB_MAX:
                        break
        return words

    # Derive, cache, return
    vocab = derive_en_vocab()
    VOCAB_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Auto-generated English vocab — do not edit manually"] + vocab
    cache_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return vocab


# ---------------------------------------------------------------------------
# Hinglish vocab
# ---------------------------------------------------------------------------


def parse_hinglish_file(path: Path | None = None) -> list[tuple[str, str]]:
    """
    Parse hinglish.txt → list of (romanized_word, english_anchor) tuples.

    Lines starting with # are comments. Blank lines are skipped.
    Entries with missing tabs produce a ValueError to catch malformed lines early.
    """
    fp = path or (VOCAB_DIR / "hinglish.txt")
    result: list[tuple[str, str]] = []
    for lineno, raw in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" not in line:
            raise ValueError(f"hinglish.txt line {lineno}: missing tab separator: {line!r}")
        word, anchor = line.split("\t", 1)
        result.append((word.strip().lower(), anchor.strip().lower()))
    return result


def _filter_en_for_hien(profanity_en: frozenset[str]) -> list[str]:
    """
    Return top HIEN_EN_TOP_N English words suitable for the hi-en vocab.

    Uses the cached en.txt to avoid re-running wordfreq.
    Falls back to deriving inline if en.txt is not yet built.
    """
    cache_path = VOCAB_DIR / "en.txt"
    if cache_path.exists():
        words: list[str] = []
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            w = line.strip()
            if w and not w.startswith("#"):
                wl = w.lower()
                if _is_valid_en_word(wl, profanity_en):
                    words.append(wl)
                    if len(words) >= HIEN_EN_TOP_N:
                        break
        return words

    # en.txt not yet built — derive a small slice inline
    from wordfreq import top_n_list

    raw = top_n_list("en", HIEN_EN_TOP_N * 3)  # over-sample to account for filter losses
    filtered: list[str] = []
    for w in raw:
        wl = w.lower()
        if _is_valid_en_word(wl, profanity_en):
            filtered.append(wl)
            if len(filtered) >= HIEN_EN_TOP_N:
                break
    return filtered


def load_hien_vocab() -> list[str]:
    """
    Return the combined hi-en vocabulary (deduplicated, profanity-filtered).

    Order: Hinglish words first (preserves curated ordering), then English top-N.
    Deduplication is exact-string (lowercased) — "dost" from hinglish and
    a hypothetical "dost" from English would be merged to one entry.
    """
    profanity_en = load_en_profanity()
    profanity_hi = load_hi_profanity()
    combined_profanity = profanity_en | profanity_hi

    hi_pairs = parse_hinglish_file()
    # Deduplicate within Hinglish list (hinglish.txt may have same romanization twice
    # with different anchor meanings; keep first occurrence).
    seen_hi: set[str] = set()
    hi_words: list[str] = []
    for w, _ in hi_pairs:
        if w not in combined_profanity and w not in seen_hi:
            hi_words.append(w)
            seen_hi.add(w)

    en_words = _filter_en_for_hien(profanity_en)

    seen: set[str] = set(hi_words)
    combined = list(hi_words)
    for w in en_words:
        if w not in seen and w not in combined_profanity:
            combined.append(w)
            seen.add(w)
    return combined
