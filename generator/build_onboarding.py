from __future__ import annotations

"""
Mindmeld onboarding-puzzle builder CLI (first-session hook, spec-first-session-hook.md).

Usage:
    python build_onboarding.py [--out ../payloads]

For each language (en, hi-en), builds ONE dedicated onboarding puzzle — a
first-run-only puzzle shown to brand-new players before they ever see the
calendar daily. Content lives in generator/onboarding/:
  secrets_{lang}.txt  — exactly one secret word (same format/conventions as
                        vocab/secrets_{lang}.txt and packs/{pack}/secrets_{lang}.txt)
  clues_{lang}.txt    — exactly one clue, keyed to that secret

Content is authored, embedding-validated, and APPROVED FINAL (GG review, see
spec-first-session-hook.md and the header comments in onboarding/*.txt); this
script validates it at build time but never mutates it.

The onboarding puzzle reuses the daily v3 payload schema via
payload.build_pack_payload (pack="onboarding", idx=1, key="onboarding-001" —
same namespacing scheme themed packs use) but overrides "maxGuesses" to a
fixed, generous ONBOARDING_MAX_GUESSES (see config.py) instead of the
par-derived daily/pack formula — a first-session win must be near-guaranteed.

Output:
    {out}/onboarding/{lang}.json.gz   (flat — one puzzle per lang, not the
                                        packs NNN scheme)
"""

import argparse
import sys
from pathlib import Path

# Script-mode path setup: ensures local modules are importable when run as
# `python build_onboarding.py` from any working directory (not just from generator/).
# This must run before the local imports below.
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np  # noqa: E402
from numpy.typing import NDArray  # noqa: E402

from build_packs import aliases_for_secret, clue_leak_reason  # noqa: E402
from config import (  # noqa: E402
    EN_MAX_GZIP_BYTES,
    GENERATOR_DIR,
    HIEN_MAX_GZIP_BYTES,
    ONBOARDING_MAX_GUESSES,
)
from embeddings import embed_vocab  # noqa: E402
from payload import _gzip_json, build_pack_payload  # noqa: E402
from profanity import is_profane, load_en_profanity, load_hi_profanity  # noqa: E402
from vocab import load_en_vocab, load_hien_vocab  # noqa: E402

LANG_LOADERS = {
    "en": load_en_vocab,
    "hi-en": load_hien_vocab,
}

# Reused as an informational size reference — the onboarding payload carries
# the full vocab word-map just like a daily payload, so it is NOT tiny in
# absolute terms; what's "tiny" is the marginal footprint (one extra file per
# lang, not a whole calendar of them).
SIZE_TARGETS = {
    "en": EN_MAX_GZIP_BYTES,
    "hi-en": HIEN_MAX_GZIP_BYTES,
}

ONBOARDING_CONTENT_DIR = GENERATOR_DIR / "onboarding"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mindmeld onboarding-puzzle builder")
    parser.add_argument(
        "--out",
        type=str,
        default="../payloads",
        help="Output directory for the onboarding payloads",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Content loading + validation
# ---------------------------------------------------------------------------


def _load_lines(path: Path) -> list[str]:
    """
    Parse an onboarding content file: skip comments/blanks.

    Mirrors packs._load_lines' parsing convention. Duplicated (not imported)
    for the same reason packs.py duplicates it from schedule.py/clues.py: a
    five-line rule not worth coupling the onboarding content path to the
    themed-pack module.
    """
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return lines


def load_onboarding_content(
    lang: str, content_dir: Path = ONBOARDING_CONTENT_DIR
) -> tuple[str, str]:
    """
    Load the single (secret, clue) pair for one language's onboarding puzzle.

    Raises ValueError if either file doesn't contain exactly one entry.
    """
    secrets = [s.lower() for s in _load_lines(content_dir / f"secrets_{lang}.txt")]
    clues = _load_lines(content_dir / f"clues_{lang}.txt")

    if len(secrets) != 1:
        raise ValueError(f"[onboarding/{lang}] expected exactly 1 secret, found {len(secrets)}")
    if len(clues) != 1:
        raise ValueError(f"[onboarding/{lang}] expected exactly 1 clue, found {len(clues)}")

    return secrets[0], clues[0]


def validate_onboarding_content(lang: str, vocab: list[str], secret: str, clue: str) -> None:
    """
    Validate one language's onboarding secret + clue.

    Checks (raises ValueError on failure):
      - secret is present in vocab
      - secret is not in the profanity blocklist
      - clue does not leak the secret (or any hi-en alias) — the same
        spoiler gate build_packs.py applies to daily/pack content
    """
    if secret not in vocab:
        raise ValueError(f"[onboarding/{lang}] secret {secret!r} not in vocab")

    profanity_en = load_en_profanity()
    profanity_hi = load_hi_profanity()
    profanity = profanity_en | profanity_hi if lang == "hi-en" else profanity_en
    if is_profane(secret, profanity):
        raise ValueError(f"[onboarding/{lang}] secret {secret!r} is in profanity blocklist")

    aliases = aliases_for_secret(secret, lang)
    leak = clue_leak_reason(clue, secret, aliases)
    if leak is not None:
        raise ValueError(
            f"[onboarding/{lang}] clue leaks secret {secret!r}: {leak}\nClue: {clue!r}"
        )


# ---------------------------------------------------------------------------
# Build + write
# ---------------------------------------------------------------------------


def build_onboarding_payload(
    lang: str,
    vocab: list[str],
    matrix: NDArray[np.float32],
    content_dir: Path = ONBOARDING_CONTENT_DIR,
) -> dict:
    """
    Build the onboarding payload dict for one language from already-loaded
    vocab/matrix.

    Loads + validates content, builds the payload via payload.build_pack_payload
    (pack="onboarding", idx=1), then overrides "maxGuesses" to the fixed
    ONBOARDING_MAX_GUESSES budget. Callers that already have vocab/matrix
    loaded (e.g. publish.py, sharing the daily build's embeddings) should use
    this directly instead of re-embedding via build_and_write_onboarding.
    """
    secret, clue = load_onboarding_content(lang, content_dir)
    validate_onboarding_content(lang, vocab, secret, clue)

    key = "onboarding-001"
    payload = build_pack_payload(vocab, matrix, secret, lang, key, "onboarding", 1, clue=clue)
    payload["maxGuesses"] = ONBOARDING_MAX_GUESSES
    return payload


def write_onboarding_payload(payload: dict, out_dir: Path, lang: str) -> Path:
    """
    Gzip-compress and write `payload` to out_dir/onboarding/{lang}.json.gz.

    Flat layout (not the packs NNN scheme) — exactly one onboarding puzzle
    per language, so no index-based nesting is needed.
    """
    onboarding_dir = out_dir / "onboarding"
    onboarding_dir.mkdir(parents=True, exist_ok=True)
    out_path = onboarding_dir / f"{lang}.json.gz"
    out_path.write_bytes(_gzip_json(payload))
    return out_path


def build_and_write_onboarding(
    lang: str,
    vocab: list[str],
    matrix: NDArray[np.float32],
    out_dir: Path,
) -> Path:
    """Build the onboarding payload for `lang` from loaded vocab/matrix and write it."""
    payload = build_onboarding_payload(lang, vocab, matrix)
    out_path = write_onboarding_payload(payload, out_dir, lang)
    file_bytes = out_path.stat().st_size
    target = SIZE_TARGETS[lang]
    print(
        f"  [onboarding/{lang}] {file_bytes:,}B "
        f"({100.0 * file_bytes / target:.1f}% of the {target:,}B daily size target)"
    )
    return out_path


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the onboarding-puzzle builder CLI."""
    args = _parse_args(argv)
    out_dir = Path(args.out).resolve()

    print(f"Building onboarding puzzle(s) for langs: {list(LANG_LOADERS)}")
    print(f"Output directory: {out_dir}")

    for lang in LANG_LOADERS:
        print(f"\n[onboarding/{lang}] Loading vocab...")
        vocab = LANG_LOADERS[lang]()
        print(f"[onboarding/{lang}] Vocab size: {len(vocab):,}")
        print(f"[onboarding/{lang}] Embedding vocab (may load model on first run)...")
        matrix = embed_vocab(vocab, lang, show_progress=True)

        try:
            build_and_write_onboarding(lang, vocab, matrix, out_dir)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)

    print("\nOnboarding build complete.")


if __name__ == "__main__":
    main()
