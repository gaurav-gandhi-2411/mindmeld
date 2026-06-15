from __future__ import annotations

"""
Mindmeld puzzle generator CLI.

Usage:
    python build.py --days 14 --langs en,hi-en [--start-date YYYY-MM-DD] [--out ../payloads]

For each language:
  1. Load vocab (from cache or derive).
  2. Embed vocab ONCE (from disk cache or model inference).
  3. For each scheduled day:
     a. Look up secret word from schedule.
     b. Compute cosine sims vs secret vector (single matrix-vector dot).
     c. Rank and emit gzipped JSON payload.
  4. Emit manifest.json.

Payload size warnings are printed but do not abort the build unless
--strict-sizes is passed.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Script-mode path setup: ensures local modules are importable when run as
# `python build.py` from any working directory (not just from generator/).
# This must run before the local imports below.
sys.path.insert(0, str(Path(__file__).parent))

from config import (  # noqa: E402
    EN_MAX_GZIP_BYTES,
    HIEN_MAX_GZIP_BYTES,
    START_DATE,
)
from embeddings import embed_vocab  # noqa: E402
from manifest import build_manifest, write_manifest  # noqa: E402
from payload import build_payload, write_payload  # noqa: E402
from clues import load_clues, clue_for_date  # noqa: E402
from schedule import load_schedule, secret_for_date, validate_schedule  # noqa: E402
from vocab import load_en_vocab, load_hien_vocab  # noqa: E402

LANG_LOADERS = {
    "en": load_en_vocab,
    "hi-en": load_hien_vocab,
}

SIZE_TARGETS = {
    "en": EN_MAX_GZIP_BYTES,
    "hi-en": HIEN_MAX_GZIP_BYTES,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mindmeld puzzle generator")
    parser.add_argument("--days", type=int, default=14, help="Number of days to generate")
    parser.add_argument(
        "--langs",
        type=str,
        default="en,hi-en",
        help="Comma-separated list of languages to generate",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Override start date (YYYY-MM-DD). Defaults to config.START_DATE.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="../payloads",
        help="Output directory for payloads and manifest",
    )
    parser.add_argument(
        "--strict-sizes",
        action="store_true",
        default=False,
        help="Fail the build if any payload exceeds its size target",
    )
    return parser.parse_args()


def _date_range(start: date, n: int) -> list[date]:
    """Return a list of n consecutive dates starting from start."""
    return [start + timedelta(days=i) for i in range(n)]


def main() -> None:
    """Main entry point for the puzzle generator CLI."""
    args = _parse_args()

    langs = [lang.strip() for lang in args.langs.split(",")]
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    start = date.fromisoformat(args.start_date) if args.start_date else START_DATE
    days = _date_range(start, args.days)

    print(f"Generating {args.days} day(s) starting {start.isoformat()} for langs: {langs}")
    print(f"Output directory: {out_dir}")

    lang_days: dict[str, list[dict]] = {}
    any_size_violation = False

    for lang in langs:
        if lang not in LANG_LOADERS:
            print(f"ERROR: unknown lang {lang!r}. Known langs: {list(LANG_LOADERS)}")
            sys.exit(1)

        print(f"\n[{lang}] Loading vocab...")
        vocab = LANG_LOADERS[lang]()
        print(f"[{lang}] Vocab size: {len(vocab):,} words")

        print(f"[{lang}] Loading schedule...")
        schedule = load_schedule(lang)
        print(f"[{lang}] Schedule length: {len(schedule)} entries")

        print(f"[{lang}] Loading clues...")
        clues = load_clues(lang)
        print(f"[{lang}] Clues loaded: {len(clues)} entries")

        print(f"[{lang}] Validating schedule against vocab...")
        try:
            validate_schedule(lang, vocab, schedule)
            print(f"[{lang}] Schedule validation passed.")
        except ValueError as exc:
            print(f"[{lang}] Schedule validation FAILED:\n{exc}")
            sys.exit(1)

        print(f"[{lang}] Embedding vocab (may load model on first run)...")
        matrix = embed_vocab(vocab, lang, show_progress=True)
        print(f"[{lang}] Embedding matrix shape: {matrix.shape}")

        day_records: list[dict] = []
        day_sizes: list[int] = []
        day_par_values: list[int] = []
        day_max_guesses_values: list[int] = []

        for puzzle_date in days:
            secret = secret_for_date(puzzle_date, lang, schedule)
            clue = clue_for_date(puzzle_date, lang, clues)
            payload = build_payload(vocab, matrix, secret, lang, puzzle_date, clue=clue)
            out_path = write_payload(payload, out_dir, lang, puzzle_date)
            file_bytes = out_path.stat().st_size
            day_sizes.append(file_bytes)
            day_par_values.append(payload["parGuesses"])
            day_max_guesses_values.append(payload["maxGuesses"])

            target = SIZE_TARGETS[lang]
            size_ok = file_bytes <= target
            status = "OK" if size_ok else "WARN: exceeds target"
            if not size_ok:
                any_size_violation = True
                if args.strict_sizes:
                    print(f"  [{puzzle_date}] {file_bytes:,}B - FAIL (target {target:,}B)")
                else:
                    print(f"  [{puzzle_date}] {file_bytes:,}B - {status} (target {target:,}B)")
            else:
                print(f"  [{puzzle_date}] {file_bytes:,}B - {status}")

            rel_path = str(out_path.relative_to(out_dir)).replace("\\", "/")
            day_records.append(
                {"date": puzzle_date.isoformat(), "file": rel_path, "bytes": file_bytes}
            )

        par_sorted = sorted(day_par_values)
        par_min = par_sorted[0]
        par_median = par_sorted[len(par_sorted) // 2]
        par_max = par_sorted[-1]
        print(
            f"[{lang}] Par distribution: min={par_min} median={par_median} max={par_max} "
            f"(target median 8-12, max 15)"
        )

        mg_sorted = sorted(day_max_guesses_values)
        mg_min = mg_sorted[0]
        mg_median = mg_sorted[len(mg_sorted) // 2]
        mg_max = mg_sorted[-1]
        print(
            f"[{lang}] maxGuesses distribution: min={mg_min} median={mg_median} max={mg_max}"
        )

        lang_days[lang] = day_records
        print(
            f"[{lang}] Size range: {min(day_sizes):,}B - {max(day_sizes):,}B "
            f"(target <={SIZE_TARGETS[lang]:,}B)"
        )

    # Emit manifest
    manifest = build_manifest(lang_days)
    manifest_path = write_manifest(manifest, out_dir)
    print(f"\nManifest written: {manifest_path}")

    if any_size_violation and args.strict_sizes:
        print("\nBuild FAILED: size targets exceeded (--strict-sizes mode).")
        sys.exit(1)

    print("\nBuild complete.")


if __name__ == "__main__":
    main()
