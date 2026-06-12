from __future__ import annotations

"""
Secret-word schedule for Mindmeld puzzles.

Secrets are hand-curated in vocab/secrets_{lang}.txt, one word per line.
The schedule is cyclic: day D uses line[(D - START_DATE).days % len(schedule)].

Both lang schedules are translation-paired line-by-line (same concept, same line)
to enable a shared social moment across English and Hinglish editions.

Validation ensures:
  - Every secret word is present in its lang vocab (raises if missing — do not
    silently add, as that could introduce unembedded words).
  - No secret appears in the profanity blocklist.
"""

from datetime import date
from pathlib import Path

from config import START_DATE, VOCAB_DIR
from profanity import load_en_profanity, load_hi_profanity


def load_schedule(lang: str, path: Path | None = None) -> list[str]:
    """
    Load and return the secret-word schedule for `lang`.

    Words are stripped of whitespace and lowercased.
    Comment lines (starting with #) and blank lines are skipped.
    """
    fp = path or (VOCAB_DIR / f"secrets_{lang}.txt")
    words: list[str] = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            words.append(stripped.lower())
    return words


def secret_for_date(puzzle_date: date, lang: str, schedule: list[str] | None = None) -> str:
    """
    Return the secret word for `puzzle_date` in `lang`.

    Uses modular arithmetic on days elapsed since START_DATE so the schedule
    cycles indefinitely and future dates are always defined.
    """
    if schedule is None:
        schedule = load_schedule(lang)
    if not schedule:
        raise ValueError(f"Empty schedule for lang={lang!r}")
    delta = (puzzle_date - START_DATE).days
    return schedule[delta % len(schedule)]


def validate_schedule(
    lang: str,
    vocab: list[str],
    schedule: list[str] | None = None,
) -> list[str]:
    """
    Validate schedule entries against vocab and profanity blocklists.

    Returns the validated schedule (same list, all entries confirmed safe).
    Raises ValueError if any entry fails validation — the build must not
    silently skip or auto-correct secret words, because the curated list
    is the source of truth for puzzle quality.
    """
    if schedule is None:
        schedule = load_schedule(lang)

    vocab_set = set(vocab)
    if lang == "hi-en":
        profanity = load_en_profanity() | load_hi_profanity()
    else:
        profanity = load_en_profanity()

    errors: list[str] = []
    for i, word in enumerate(schedule):
        if word in profanity:
            errors.append(f"Line {i + 1}: secret {word!r} is in profanity blocklist")
        if word not in vocab_set:
            errors.append(f"Line {i + 1}: secret {word!r} is NOT in {lang} vocab")

    if errors:
        raise ValueError(f"Schedule validation failed for lang={lang!r}:\n" + "\n".join(errors))

    return schedule
