from __future__ import annotations

"""
Spoiler gate: verify no clue leaks its own secret, alias, or morphological
variant across the full 60-day window for both languages, and across all
themed-pack content (Phase 6c) that has been authored so far.

Reuses build_packs.clue_leak_reason for the substring + token-level checks
(the same predicate build_packs.py uses to gate pack builds at build time),
which in turn reuses payload._is_morphological_variant (same logic that
caught 'oceans' for 'ocean' in the hint filter).
"""

import pytest

from build_packs import aliases_for_secret, clue_leak_reason
from clues import load_clues
from packs import load_pack_clues, load_pack_secrets, load_packs_meta
from schedule import load_schedule


def _get_aliases(secret: str, lang: str) -> list[str]:
    """Return all aliases for `secret` in `lang` (hi-en only; returns [] for en)."""
    return aliases_for_secret(secret, lang)


@pytest.mark.parametrize("lang", ["en", "hi-en"])
def test_spoiler_gate_full_window(lang: str) -> None:
    """No clue leaks its own secret, alias, or morphological variant."""
    clues = load_clues(lang)
    schedule = load_schedule(lang)

    assert len(clues) == len(schedule), (
        f"[{lang}] clue/schedule length mismatch: {len(clues)} clues vs {len(schedule)} secrets"
    )

    failures: list[str] = []
    for i, (clue, secret) in enumerate(zip(clues, schedule, strict=True)):
        aliases = _get_aliases(secret, lang)
        leak = clue_leak_reason(clue, secret, aliases)
        if leak is not None:
            failures.append(
                f"  [{lang}] line {i + 1}: secret='{secret}' — {leak}\n  Clue: {clue!r}"
            )

    assert not failures, f"Spoiler gate FAILED for {len(failures)} clue(s):\n" + "\n".join(
        failures
    )


def _pack_lang_cases() -> list[tuple[str, str]]:
    """Return (pack_id, lang) pairs for every pack × lang declared in packs.json."""
    return [(pack.id, lang) for pack in load_packs_meta() for lang in pack.langs]


@pytest.mark.parametrize(("pack_id", "lang"), _pack_lang_cases())
def test_spoiler_gate_pack_content(pack_id: str, lang: str) -> None:
    """
    No pack clue leaks its own secret, alias, or morphological variant.

    Packs with comment-only content (0 secrets, e.g. bollywood pending
    authorship) are skipped — this test automatically starts gating each
    pack's clues the moment real content is authored, with no test changes
    required.
    """
    packs_by_id = {pack.id: pack for pack in load_packs_meta()}
    pack = packs_by_id[pack_id]

    secrets = load_pack_secrets(pack, lang)
    clues = load_pack_clues(pack, lang)

    if not secrets:
        pytest.skip(f"[{pack_id}/{lang}] no content authored yet")

    assert len(clues) == len(secrets), (
        f"[{pack_id}/{lang}] clue/secret count mismatch: "
        f"{len(clues)} clues vs {len(secrets)} secrets"
    )

    failures: list[str] = []
    for i, (secret, clue) in enumerate(zip(secrets, clues, strict=True)):
        aliases = _get_aliases(secret, lang)
        leak = clue_leak_reason(clue, secret, aliases)
        if leak is not None:
            failures.append(
                f"  [{pack_id}/{lang}] line {i + 1}: secret='{secret}' — {leak}\n"
                f"  Clue: {clue!r}"
            )

    assert not failures, f"Spoiler gate FAILED for {len(failures)} clue(s):\n" + "\n".join(
        failures
    )
