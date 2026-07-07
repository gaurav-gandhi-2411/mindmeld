"""Fail loudly if the generated web plugin registrant is missing a Firebase
web plugin — guards against silent Firebase web registration failures.

Background: 2026-07-07, creating a social group hung/failed live on
playmindmeld.vercel.app with a firebase_auth "channel-error" (Pigeon platform
channel, meaning FirebaseAuthWeb never became the active platform instance).
The eventual root cause was an unrelated Firebase Auth config issue (the
deploy domain wasn't in the project's authorized-domains list) — but during
diagnosis it was hard to quickly rule OUT "the web plugin registrant is
missing firebase_auth_web" as a cause, partly because grepping the *compiled*
--release bundle for class names is unreliable (dart2js renames identifiers
under minification; only string literals survive). This script checks the
*source* registrant Flutter generates, before any compilation, so the check
is minification-proof.

Usage:
    uv run python scripts/check_web_plugin_registrant.py --project-dir app
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Web plugins this app depends on for Firebase — every one of these classes
# must appear in the generated registrant, or Firebase.* web calls silently
# fall back to the native (non-functional-on-web) platform implementation.
REQUIRED_REGISTRATIONS: tuple[str, ...] = (
    "FirebaseCoreWeb",
    "FirebaseAuthWeb",
    "FirebaseFirestoreWeb",
    "FirebaseAnalyticsWeb",
    "FirebaseMessagingWeb",
)

# Known locations Flutter has generated the web plugin registrant to across
# versions — check whichever exist; at least one must be present and correct.
CANDIDATE_RELATIVE_PATHS: tuple[str, ...] = (
    ".dart_tool/dartpad/web_plugin_registrant.dart",
)


def _candidate_paths(project_dir: Path) -> list[Path]:
    paths = [project_dir / rel for rel in CANDIDATE_RELATIVE_PATHS]
    # Also check every hash-keyed flutter_build/*/web_plugin_registrant.dart.
    flutter_build = project_dir / ".dart_tool" / "flutter_build"
    if flutter_build.is_dir():
        paths.extend(sorted(flutter_build.glob("*/web_plugin_registrant.dart")))
    return [p for p in paths if p.is_file()]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir",
        required=True,
        type=Path,
        help="Flutter project directory (e.g. app) — run AFTER `flutter pub get` "
        "or `flutter build web` so the registrant has been generated.",
    )
    args = parser.parse_args(argv)

    project_dir: Path = args.project_dir.resolve()
    candidates = _candidate_paths(project_dir)

    if not candidates:
        print(
            "ERROR: no web_plugin_registrant.dart found under .dart_tool/. "
            "Run `flutter pub get` (or `flutter build web`) first.",
            file=sys.stderr,
        )
        sys.exit(1)

    ok = False
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        missing = [cls for cls in REQUIRED_REGISTRATIONS if cls not in text]
        if not missing:
            print(f"OK: {path} registers all of {REQUIRED_REGISTRATIONS}")
            ok = True
        else:
            print(f"  {path} is missing: {missing}")

    if not ok:
        print(
            "\nERROR: no generated web plugin registrant references all of "
            f"{REQUIRED_REGISTRATIONS}. A Firebase web plugin failed to wire in — "
            "Firebase.* calls on web will silently fall back to the native "
            "platform channel implementation and throw '[x/channel-error]' at "
            "runtime instead of working. Try `flutter clean && flutter pub get`.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
