from __future__ import annotations

"""
Mindmeld payload publisher CLI.

Usage:
    uv run python publish.py --days 30 [--langs en,hi-en]
                             [--payloads-repo C:\\path\\to\\mindmeld-payloads]
                             [--dry-run]

Steps:
  1. Run the build (via build.main internals) into a temporary output directory.
  2. Sync en/, hi-en/, manifest.json into the payloads repo working tree
     (copy/overwrite; never delete unknown files like README.md or .nojekyll).
  3. In the payloads repo: git add -A, commit with a conventional message, and
     git push origin main. If nothing changed, skip commit/push and say so.

--dry-run is fully read-only: reports what would be copied/committed without
writing into the payloads repo or executing any git mutating commands.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

# Script-mode path setup so local modules are importable when run from any cwd.
sys.path.insert(0, str(Path(__file__).parent))

from config import START_DATE  # noqa: E402

# Languages that have a corresponding subdirectory in the payloads repo.
_PAYLOAD_LANGS: tuple[str, ...] = ("en", "hi-en")

# Default payloads repo path (sibling directory).
_DEFAULT_PAYLOADS_REPO = Path(__file__).parent.parent.parent / "mindmeld-payloads"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Mindmeld payloads and publish to the payloads git repo."
    )
    parser.add_argument("--days", type=int, default=30, help="Number of days to generate")
    parser.add_argument(
        "--langs",
        type=str,
        default="en,hi-en",
        help="Comma-separated list of languages to generate (default: en,hi-en)",
    )
    parser.add_argument(
        "--payloads-repo",
        type=str,
        default=str(_DEFAULT_PAYLOADS_REPO),
        help="Path to the mindmeld-payloads git working tree",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Read-only: report what would be copied/committed without writing anything",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Build step — call build internals directly (no subprocess)
# ---------------------------------------------------------------------------


def _run_build(
    days: int,
    langs: list[str],
    out_dir: Path,
    start: date = START_DATE,
) -> None:
    """
    Invoke the build pipeline directly (no subprocess spawn).

    Imports build-module internals and calls them with the given parameters.
    This avoids a double Python interpreter start and gives us a proper
    in-process traceback on failure.
    """
    from datetime import timedelta  # noqa: I001

    import build as _build  # local module inside generator/

    from clues import clue_for_date, load_clues
    from embeddings import embed_vocab
    from manifest import build_manifest, write_manifest
    from payload import build_payload, write_payload
    from schedule import load_schedule, secret_for_date, validate_schedule

    out_dir.mkdir(parents=True, exist_ok=True)
    days_list: list[date] = [start + timedelta(days=i) for i in range(days)]

    lang_days: dict[str, list[dict]] = {}

    for lang in langs:
        if lang not in _build.LANG_LOADERS:
            print(f"ERROR: unknown lang {lang!r}. Known: {list(_build.LANG_LOADERS)}")
            sys.exit(1)

        print(f"[{lang}] Loading vocab...")
        vocab = _build.LANG_LOADERS[lang]()
        print(f"[{lang}] Vocab size: {len(vocab):,}")

        print(f"[{lang}] Loading schedule...")
        schedule = load_schedule(lang)

        print(f"[{lang}] Loading clues...")
        clues = load_clues(lang)

        print(f"[{lang}] Validating schedule...")
        try:
            validate_schedule(lang, vocab, schedule)
        except ValueError as exc:
            print(f"[{lang}] Schedule validation FAILED:\n{exc}")
            sys.exit(1)

        print(f"[{lang}] Embedding vocab (may load model on first run)...")
        matrix = embed_vocab(vocab, lang, show_progress=True)

        day_records: list[dict] = []
        for puzzle_date in days_list:
            secret = secret_for_date(puzzle_date, lang, schedule)
            clue = clue_for_date(puzzle_date, lang, clues)
            payload = build_payload(vocab, matrix, secret, lang, puzzle_date, clue=clue)
            out_path = write_payload(payload, out_dir, lang, puzzle_date)
            file_bytes = out_path.stat().st_size
            rel = str(out_path.relative_to(out_dir)).replace("\\", "/")
            day_records.append({"date": puzzle_date.isoformat(), "file": rel, "bytes": file_bytes})
            print(f"  [{lang}] {puzzle_date} -> {file_bytes:,}B")

        lang_days[lang] = day_records

    manifest = build_manifest(lang_days)
    manifest_path = write_manifest(manifest, out_dir)
    print(f"\nManifest written: {manifest_path}")


# ---------------------------------------------------------------------------
# Sync step — copy payload outputs into payloads repo working tree
# ---------------------------------------------------------------------------


def _collect_sync_plan(
    src_dir: Path,
    payloads_repo: Path,
    langs: list[str],
) -> list[tuple[Path, Path]]:
    """
    Return a list of (src_file, dst_file) pairs that represent the sync plan.

    Covers each lang subdirectory and manifest.json. Does NOT touch README.md,
    .nojekyll, or any file not produced by the build.
    """
    plan: list[tuple[Path, Path]] = []

    for lang in langs:
        if lang not in _PAYLOAD_LANGS:
            continue
        src_lang_dir = src_dir / lang
        dst_lang_dir = payloads_repo / lang
        if not src_lang_dir.exists():
            continue
        for src_file in sorted(src_lang_dir.iterdir()):
            if src_file.is_file():
                plan.append((src_file, dst_lang_dir / src_file.name))

    src_manifest = src_dir / "manifest.json"
    if src_manifest.exists():
        plan.append((src_manifest, payloads_repo / "manifest.json"))

    return plan


def _apply_sync(plan: list[tuple[Path, Path]]) -> None:
    """Copy each (src, dst) pair, creating parent directories as needed."""
    for src, dst in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        print(f"  copied {src.name} -> {dst}")


def _print_sync_plan(plan: list[tuple[Path, Path]]) -> None:
    """Print what would be copied without doing it."""
    for src, dst in plan:
        print(f"  [dry-run] would copy {src.name} -> {dst}")


# ---------------------------------------------------------------------------
# Commit message formatting
# ---------------------------------------------------------------------------


def _commit_message(dates: list[date], langs: list[str]) -> str:
    """
    Build the conventional commit message for a payload drop.

    Format: chore: payload drop <first-date>..<last-date> (<langs>) [skip ci]

    [skip ci] is correct here: this is an automated data-only commit that does
    not need CI re-run. See CLAUDE.md rule 34 for the policy.
    """
    if not dates:
        raise ValueError("dates list must not be empty")
    first = dates[0].isoformat()
    last = dates[-1].isoformat()
    langs_str = ",".join(langs)
    return f"chore: payload drop {first}..{last} ({langs_str}) [skip ci]"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """
    Run a git command with the given cwd, capturing stdout/stderr.

    Raises SystemExit with a non-zero code on failure, printing git's stderr.
    """
    cmd = ["git", *args]
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: git {' '.join(args)} failed (exit {result.returncode})")
        if result.stderr.strip():
            print(result.stderr.strip())
        sys.exit(result.returncode)
    return result


def _git_has_changes(payloads_repo: Path) -> bool:
    """Return True if the payloads repo working tree has staged or unstaged changes."""
    # git status --porcelain exits 0 with empty output when clean
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(payloads_repo),
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def _commit_and_push(payloads_repo: Path, message: str) -> None:
    """Stage all, commit, and push origin main."""
    _git(["add", "-A"], cwd=payloads_repo)

    if not _git_has_changes(payloads_repo):
        # Nothing staged after git add -A means git status --porcelain was already
        # empty before add (clean tree). The pre-add check covers this, but be safe.
        print("No changes to commit — payloads repo is already up to date.")
        return

    _git(["commit", "-m", message], cwd=payloads_repo)
    print(f"Committed: {message}")

    _git(["push", "origin", "main"], cwd=payloads_repo)
    print("Pushed to origin main.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Publish entry point — called by `uv run publish` and tests."""
    args = _parse_args(argv)

    langs = [lang.strip() for lang in args.langs.split(",") if lang.strip()]
    payloads_repo = Path(args.payloads_repo).resolve()
    dry_run: bool = args.dry_run

    if not payloads_repo.exists():
        print(f"ERROR: payloads repo not found: {payloads_repo}")
        sys.exit(1)

    start = START_DATE
    days_list: list[date] = [start + timedelta(days=i) for i in range(args.days)]
    commit_msg = _commit_message(days_list, langs)

    print(f"{'[DRY-RUN] ' if dry_run else ''}Publishing {args.days} day(s) for langs: {langs}")
    print(f"Payloads repo: {payloads_repo}")
    print(f"Commit message (if changes): {commit_msg}")

    with tempfile.TemporaryDirectory(prefix="mindmeld-publish-") as tmp:
        tmp_dir = Path(tmp)

        # Step 1: Build
        print("\n--- Build ---")
        _run_build(days=args.days, langs=langs, out_dir=tmp_dir, start=start)

        # Step 2: Collect sync plan
        plan = _collect_sync_plan(src_dir=tmp_dir, payloads_repo=payloads_repo, langs=langs)
        print(f"\n--- Sync ({len(plan)} file(s)) ---")

        if dry_run:
            _print_sync_plan(plan)
            print("\n[dry-run] Checking for would-be changes (comparing with payloads repo)...")
            changed = _count_changed_files(plan)
            print(f"[dry-run] {changed} file(s) differ from current payloads repo state.")
            print(f"[dry-run] Would commit: {commit_msg}")
            print("[dry-run] Would push to origin main.")
            print("\n[dry-run] No files written, no git commands executed.")
            return

        # Step 3: Apply sync
        _apply_sync(plan)

        # Step 4: Commit and push (skip if clean)
        print("\n--- Git ---")
        if not _git_has_changes(payloads_repo):
            print("No changes detected in payloads repo — skipping commit and push.")
            return

        _commit_and_push(payloads_repo, commit_msg)
        print("\nPublish complete.")


def _count_changed_files(plan: list[tuple[Path, Path]]) -> int:
    """
    Count how many files in the sync plan differ from what is already on disk.

    Used by --dry-run to report without writing.
    """
    changed = 0
    for src, dst in plan:
        if not dst.exists() or src.read_bytes() != dst.read_bytes():
            changed += 1
    return changed


if __name__ == "__main__":
    main()
