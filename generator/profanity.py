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


def load_en_profanity() -> frozenset[str]:
    """Return the English profanity blocklist as a frozenset of lowercase strings."""
    return _load_blocklist(VOCAB_DIR / "profanity_en.txt")


def load_hi_profanity() -> frozenset[str]:
    """Return the romanized Hindi/Hinglish profanity blocklist as a frozenset."""
    return _load_blocklist(VOCAB_DIR / "profanity_hi.txt")


def is_profane(word: str, blocklist: frozenset[str]) -> bool:
    """Return True if the word (lowercased) appears in the blocklist."""
    return word.lower() in blocklist
