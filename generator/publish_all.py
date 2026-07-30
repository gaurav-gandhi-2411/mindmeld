from __future__ import annotations

"""
Publish daily + onboarding + themed-pack payloads together, for a model-swap
drop where everything for a language needs to move as one atomic commit.

publish.py's own docstring documents packs as "orchestrated separately" (its
`main()` owns an ephemeral tempdir that build_packs.py has no hook into) --
this script closes that gap by reusing publish.py's and build_packs.py's
existing, tested internals against ONE shared temp directory instead of
duplicating their logic: `publish._run_build` (daily + onboarding) into a
persistent tempdir, then `build_packs.main` (packs) into the SAME dir, then
`publish._collect_sync_plan` / `_apply_sync` / `_commit_and_push`.

Usage:
    uv run python publish_all.py --days 60 --langs hi-en
        [--payloads-repo C:\\path\\to\\mindmeld-payloads] [--dry-run]
"""

import argparse
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import build_packs  # noqa: E402
import publish  # noqa: E402
from config import START_DATE  # noqa: E402

_DEFAULT_PAYLOADS_REPO = Path(__file__).parent.parent.parent / "mindmeld-payloads"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--langs", type=str, default="hi-en")
    parser.add_argument("--payloads-repo", type=str, default=str(_DEFAULT_PAYLOADS_REPO))
    parser.add_argument("--strict-sizes", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    langs = [lang.strip() for lang in args.langs.split(",") if lang.strip()]
    payloads_repo = Path(args.payloads_repo).resolve()
    dry_run: bool = args.dry_run

    if not payloads_repo.exists():
        print(f"ERROR: payloads repo not found: {payloads_repo}")
        sys.exit(1)

    start = START_DATE
    days_list: list[date] = [start + timedelta(days=i) for i in range(args.days)]
    commit_msg = publish._commit_message(days_list, langs) + " + packs"

    print(f"{'[DRY-RUN] ' if dry_run else ''}Publishing {args.days} day(s) + packs for: {langs}")
    print(f"Payloads repo: {payloads_repo}")
    print(f"Commit message (if changes): {commit_msg}")

    with tempfile.TemporaryDirectory(prefix="mindmeld-publish-all-") as tmp:
        tmp_dir = Path(tmp)

        print("\n--- Build: daily + onboarding ---")
        publish._run_build(days=args.days, langs=langs, out_dir=tmp_dir, start=start)

        print("\n--- Build: themed packs ---")
        pack_argv = ["--packs", "all", "--langs", ",".join(langs), "--out", str(tmp_dir)]
        if args.strict_sizes:
            pack_argv.append("--strict-sizes")
        build_packs.main(pack_argv)

        plan = publish._collect_sync_plan(src_dir=tmp_dir, payloads_repo=payloads_repo, langs=langs)
        print(f"\n--- Sync ({len(plan)} file(s)) ---")

        if dry_run:
            publish._print_sync_plan(plan)
            changed = publish._count_changed_files(plan)
            print(f"\n[dry-run] {changed} file(s) differ from current payloads repo state.")
            print(f"[dry-run] Would commit: {commit_msg}")
            print("[dry-run] Would push to origin main.")
            return

        publish._apply_sync(plan)

        print("\n--- Git ---")
        if not publish._git_has_changes(payloads_repo):
            print("No changes detected in payloads repo -- skipping commit and push.")
            return

        publish._commit_and_push(payloads_repo, commit_msg)
        print("\nPublish complete.")


if __name__ == "__main__":
    main()
