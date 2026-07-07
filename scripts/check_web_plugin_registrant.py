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

Second incident, 2026-07-08: this script originally passed if ANY candidate
registrant file contained every required class — including
`.dart_tool/dartpad/web_plugin_registrant.dart`, which is NOT produced by (or
consumed by) the real `flutter build web` pipeline; it's a side artifact of
IDE/analysis tooling. That let a genuinely STALE `.dart_tool/flutter_build/
<hash>/web_plugin_registrant.dart` — the file actually compiled into
main.dart.js — silently ship without `FirebaseMessagingWeb` registered, while
the irrelevant dartpad copy (which happened to be regenerated more recently
and DID have it) made this script print "OK". The result: `getToken()` threw
`MissingPluginException` live, because `FirebaseMessagingPlatform.instance`
was never actually the web implementation — the exact class of failure this
script exists to catch, except this time it looked "OK". Root-caused via a
real end-to-end opt-in attempt against the live site (headless Chrome with
notification permission pre-granted via CDP), not a test — the true owner of
this contract is whatever `flutter build web` just compiled, not source
existing anywhere on disk. Fixed: only `flutter_build/*/web_plugin_registrant.dart`
files count now (every one found must be correct — there is no such thing as
"one stale one is fine"), and a `flutter clean` before rebuilding is the
standard remedy since stale hash-keyed cache dirs are the recurring cause.

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

def _candidate_paths(project_dir: Path) -> list[Path]:
    # ONLY flutter_build/<hash>/web_plugin_registrant.dart files count — these
    # are what `flutter build web` actually compiles. `.dart_tool/dartpad/` is
    # deliberately excluded (see module docstring's 2026-07-08 incident): it's
    # not part of the real build pipeline and checking it created a false
    # sense of safety when it disagreed with the real one.
    flutter_build = project_dir / ".dart_tool" / "flutter_build"
    if not flutter_build.is_dir():
        return []
    return sorted(p for p in flutter_build.glob("*/web_plugin_registrant.dart") if p.is_file())


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

    # EVERY candidate must be correct — see module docstring's 2026-07-08
    # incident for why "at least one" is unsafe: a stale hash-keyed cache dir
    # is indistinguishable from the real one without checking all of them,
    # and any one of them could be what a given build actually compiles.
    all_ok = True
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        missing = [cls for cls in REQUIRED_REGISTRATIONS if cls not in text]
        if not missing:
            print(f"OK: {path} registers all of {REQUIRED_REGISTRATIONS}")
        else:
            print(f"  {path} is missing: {missing}")
            all_ok = False

    if not all_ok:
        print(
            "\nERROR: at least one flutter_build/*/web_plugin_registrant.dart "
            f"does not reference all of {REQUIRED_REGISTRATIONS}. A Firebase web "
            "plugin failed to wire in — Firebase.* calls on web will silently "
            "fall back to the native platform channel implementation and throw "
            "MissingPluginException or '[x/channel-error]' at runtime instead of "
            "working. This is very likely a STALE cache dir — run "
            "`flutter clean && flutter pub get` and rebuild before deploying.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
