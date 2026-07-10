from __future__ import annotations

"""
Shared EN<->hi-en secret pairing — the daily schedule pairs secrets_en.txt
line N with secrets_hi-en.txt line N (same concept, different language; see
schedule.py's module doc). This is the single source of truth for "which
hi-en secret translates which EN secret", reused by:

  - dimension1_ranking: classifies each hi-en near-tier word as a
    "translation" (word == its secret's EN pair) vs an "associate" (anything
    else) — these test different capabilities and must be reported
    separately, not blended (GG review, 2026-07-10).
  - dimension2_crosslang: the cross-language consistency dimension IS this
    pairing — parallel guess sets against translation-paired secrets.
"""

from schedule import load_schedule


def load_daily_pairs() -> list[tuple[str, str]]:
    """Return [(en_secret, hien_secret), ...] for the full daily schedule,
    in schedule order (same line number = same concept)."""
    en = load_schedule("en")
    hien = load_schedule("hi-en")
    return list(zip(en, hien, strict=True))


def en_to_hien_map() -> dict[str, str]:
    """en_secret -> hien_secret for the full daily schedule."""
    return dict(load_daily_pairs())


def hien_to_en_map() -> dict[str, str]:
    """hien_secret -> en_secret for the full daily schedule."""
    return {hien: en for en, hien in load_daily_pairs()}
