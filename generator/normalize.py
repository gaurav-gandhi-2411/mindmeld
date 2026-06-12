from __future__ import annotations

"""
Romanized-Hindi spelling normalization for Mindmeld hi-en payloads.

This is a LOOKUP-FOLDING function for hi-en — not a linguistic transcription
system or phonology model. The sole purpose is to collapse common romanization
variants onto a single canonical form so that hash lookups in the payload
`words` map succeed regardless of which common spelling the player typed.

Normalization pass order (applied once, left-to-right):
    1. Strip whitespace + lowercase
    2. chh → ch          (chh is a common over-romanized aspirate cluster)
    3. aa  → a           (long-a marker that many writers omit)
    4. ee  → i           (long-i marker)
    5. oo  → u           (long-u marker)

Each substitution is applied globally (all occurrences). The order is fixed
so that "chha" → "cha" (chh→ch first, then aa stays as-is because no "aa").

Alias file (vocab/hi-en-aliases.txt):
    Format: canonical: alias1, alias2, ...
    # comments allowed; blank lines skipped.
    The alias map is loaded on first call and cached in-process.

Public API:
    normalize(word)          - apply folding rules only
    canonical_for(word)      - normalize then check alias map; returns canonical
    load_alias_map()         - returns {alias: canonical} dict (cached)
"""

import re
from functools import lru_cache
from pathlib import Path

VOCAB_DIR = Path(__file__).parent / "vocab"
_ALIAS_FILE = VOCAB_DIR / "hi-en-aliases.txt"

# Substitution rules applied in this exact order.
# Each is (compiled_pattern, replacement_string).
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"chh"), "ch"),
    (re.compile(r"aa"), "a"),
    (re.compile(r"ee"), "i"),
    (re.compile(r"oo"), "u"),
]


def normalize(word: str) -> str:
    """
    Apply romanized-Hindi folding rules and return the normalized form.

    Rules (in order):
      lowercase + strip → chh→ch → aa→a → ee→i → oo→u

    This is a many-to-one mapping: multiple spellings fold to the same
    output. It is NOT reversible and NOT a transliteration.

    Examples:
        "BAARISH" → "barish"
        "bageecha" → "bagecha"   (ee→i, then a already present)
        "chhhata"  → "chata"     (chh→ch)
        "khushboo" → "khushbu"
    """
    result = word.strip().lower()
    for pattern, replacement in _RULES:
        result = pattern.sub(replacement, result)
    return result


@lru_cache(maxsize=1)
def load_alias_map() -> dict[str, str]:
    """
    Load vocab/hi-en-aliases.txt and return {normalized_alias: canonical} dict.

    File format:
        canonical: alias1, alias2   # optional comment
        # full-line comment
        (blank lines skipped)

    Both canonical and alias are stored in normalized form so lookups are
    normalization-idempotent. The canonical key itself is NOT added as an
    alias entry — it will match via normalize() directly.

    Cached after first call (lru_cache on the module-level function).
    """
    alias_map: dict[str, str] = {}
    if not _ALIAS_FILE.exists():
        return alias_map

    for raw_line in _ALIAS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comment
        if "#" in line:
            line = line[: line.index("#")].strip()
        if ":" not in line:
            continue
        canonical_raw, aliases_raw = line.split(":", 1)
        canonical = canonical_raw.strip().lower()
        for alias_raw in aliases_raw.split(","):
            alias = alias_raw.strip().lower()
            if not alias:
                continue
            norm_alias = normalize(alias)
            if norm_alias not in alias_map:
                alias_map[norm_alias] = canonical
            # If two canonicals collide on the same normalized alias, keep the
            # first encountered (file order). Build output notes collisions.
    return alias_map


def canonical_for(word: str, alias_map: dict[str, str] | None = None) -> str:
    """
    Return the canonical spelling for a romanized-Hindi word.

    Resolution order:
      1. normalize(word)  — apply folding rules
      2. check alias_map[normalized]  — alias-file lookup
      3. return normalized form if no alias found

    Parameters
    ----------
    word:
        Raw input as typed by the player (any case, any trailing spaces).
    alias_map:
        Pre-loaded alias map (for testing/injection). Uses load_alias_map()
        if None.

    Returns
    -------
    str
        The canonical form. If the word has no alias entry, returns normalize(word).
    """
    norm = normalize(word)
    if alias_map is None:
        alias_map = load_alias_map()
    return alias_map.get(norm, norm)
