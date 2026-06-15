from __future__ import annotations

"""Clue loading for Phase 5 — keyed line-by-line to the secret schedule."""

from datetime import date
from pathlib import Path

from config import START_DATE, VOCAB_DIR


def load_clues(lang: str, path: Path | None = None) -> list[str]:
    """Load and return the clue list for lang from vocab/clues-{lang}.txt.

    Lines starting with # and blank lines are skipped.
    """
    fp = path or (VOCAB_DIR / f"clues-{lang}.txt")
    clues: list[str] = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            clues.append(stripped)
    return clues


def clue_for_date(puzzle_date: date, lang: str, clues: list[str] | None = None) -> str:
    """Return the clue for puzzle_date in lang.

    Uses the same modular arithmetic as secret_for_date so clue[i] always
    pairs with schedule[i].
    """
    if clues is None:
        clues = load_clues(lang)
    if not clues:
        raise ValueError(f"Empty clue list for lang={lang!r}")
    delta = (puzzle_date - START_DATE).days
    return clues[delta % len(clues)]
