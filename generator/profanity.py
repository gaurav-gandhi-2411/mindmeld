from __future__ import annotations

"""
Offline profanity / slur blocklist loader.

Reads bundled text files (no external API calls, no network dependency).
Returns frozensets for O(1) lookup at build time.
"""

from pathlib import Path

from config import VOCAB_DIR


def _load_blocklist(path: Path) -> frozenset[str]:
    """Parse a blocklist file: skip comment lines and blank lines, lowercase everything."""
    words: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            words.append(stripped.lower())
    return frozenset(words)


_EN_BLOCKLIST_FILES = (
    "profanity_en.txt",
    "blocklist_ldnoobw_en.txt",  # vendored, CC-BY-4.0 -- see file header
    "blocklist_supplement_en.txt",  # curated hate/abuse terms LDNOOBW misses
)
_HI_BLOCKLIST_FILES = (
    "profanity_hi.txt",
    "blocklist_ldnoobw_hi.txt",  # vendored, CC-BY-4.0 -- see file header
    "blocklist_supplement_hi.txt",  # curated romanized slurs incl. casteist
)


def load_en_profanity() -> frozenset[str]:
    """Return the English blocklist (union of all EN files) as lowercase strings."""
    return frozenset().union(*(_load_blocklist(VOCAB_DIR / f) for f in _EN_BLOCKLIST_FILES))


def load_hi_profanity() -> frozenset[str]:
    """Return the romanized Hindi/Hinglish blocklist (union of all HI files)."""
    return frozenset().union(*(_load_blocklist(VOCAB_DIR / f) for f in _HI_BLOCKLIST_FILES))


def is_profane(word: str, blocklist: frozenset[str]) -> bool:
    """Return True if the word (lowercased) appears in the blocklist."""
    return word.lower() in blocklist
