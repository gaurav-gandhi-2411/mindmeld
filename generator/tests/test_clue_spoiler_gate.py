from __future__ import annotations

"""
Spoiler gate: verify no clue leaks its own secret, alias, or morphological
variant across the full 60-day window for both languages.

Reuses payload._is_morphological_variant for token-level checks (same logic
that caught 'oceans' for 'ocean' in the hint filter).
"""

import re
from pathlib import Path

import pytest

from clues import load_clues
from normalize import load_alias_map
from payload import _is_morphological_variant
from schedule import load_schedule


def _extract_tokens(text: str) -> list[str]:
    """Return lowercase alpha tokens longer than 2 characters from text."""
    return [t for t in re.findall(r"[a-z]+", text.lower()) if len(t) > 2]


def _clue_leaks(clue: str, secret: str, aliases: list[str]) -> str | None:
    """
    Return an error description if the clue leaks the secret, else None.

    Checks (in order):
    1. Secret (or alias) appears as a substring anywhere in the lowercased clue.
    2. Any token in the clue is a morphological variant of the secret or alias
       (e.g. 'fires' → 'fire', 'campfire' contains 'fire').
    """
    clue_lower = clue.lower()
    targets = [secret] + aliases

    for target in targets:
        # Check 1: direct substring
        if target in clue_lower:
            return f"direct substring '{target}'"

        # Check 2: token-level morphological variant
        for token in _extract_tokens(clue_lower):
            if _is_morphological_variant(token, target):
                return f"token '{token}' is morphological variant of '{target}'"

    return None


def _get_aliases(secret: str, lang: str) -> list[str]:
    """Return all aliases for `secret` in `lang` (hi-en only; returns [] for en)."""
    if lang != "hi-en":
        return []
    alias_map = load_alias_map()
    return [alias for alias, canonical in alias_map.items() if canonical == secret]


@pytest.mark.parametrize("lang", ["en", "hi-en"])
def test_spoiler_gate_full_window(lang: str) -> None:
    """No clue leaks its own secret, alias, or morphological variant."""
    clues = load_clues(lang)
    schedule = load_schedule(lang)

    assert len(clues) == len(schedule), (
        f"[{lang}] clue/schedule length mismatch: {len(clues)} clues vs {len(schedule)} secrets"
    )

    failures: list[str] = []
    for i, (clue, secret) in enumerate(zip(clues, schedule)):
        aliases = _get_aliases(secret, lang)
        leak = _clue_leaks(clue, secret, aliases)
        if leak is not None:
            failures.append(f"  [{lang}] line {i + 1}: secret='{secret}' — {leak}\n  Clue: {clue!r}")

    assert not failures, (
        f"Spoiler gate FAILED for {len(failures)} clue(s):\n" + "\n".join(failures)
    )
