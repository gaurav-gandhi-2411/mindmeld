"""Fail loudly if a production domain is missing from Firebase Auth's
authorized-domains list — guards against the 2026-07-07 class of bug.

Background: playmindmeld.vercel.app went live without ever being added to
the warmer-prod-260813 project's Identity Toolkit `authorizedDomains`. Every
firebase_auth call (starting with signInAnonymously()) then failed with a
`[firebase_auth/channel-error]` that *looked* like a web-plugin-registration
bug and cost significant diagnosis time before the real cause was found (see
the 2026-07-07 incident note in docs/firebase-setup.md). Firebase Auth adds
`localhost` and the project's own `*.firebaseapp.com`/`*.web.app` domains
automatically, but never a custom deploy domain — so this check must run
every time a new or changed production domain goes live, not just once.

This script reads the LIVE Identity Toolkit config (the same one Firebase
Auth enforces against at request time) via the Admin API — never a local
guess or a cached value — so it can't go stale the way a hardcoded domain
list would.

Auth: reuses whatever `gcloud` credentials are already active on this
machine (the same ones used for the manual `curl`/`gcloud` remediation
documented in docs/firebase-setup.md) — no separate service account or
secret to manage.

Usage:
    uv run python scripts/check_authorized_domains.py \\
        --project-id warmer-prod-260813 \\
        --domain playwarmer.vercel.app
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

IDENTITY_TOOLKIT_CONFIG_URL = (
    "https://identitytoolkit.googleapis.com/admin/v2/projects/{project_id}/config"
)


def _access_token() -> str:
    # On Windows `gcloud` resolves to a .CMD shim, which CreateProcess cannot
    # exec directly — shutil.which() honors PATHEXT to find it either way,
    # and passing the resolved path still needs shell=True to launch a .CMD.
    gcloud = shutil.which("gcloud") or "gcloud"
    try:
        result = subprocess.run(
            [gcloud, "auth", "print-access-token"],
            capture_output=True,
            text=True,
            check=True,
            shell=(sys.platform == "win32"),
        )
    except (OSError, subprocess.CalledProcessError) as e:
        print(
            "ERROR: could not get a gcloud access token (is gcloud installed and "
            f"`gcloud auth login` run?): {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    return result.stdout.strip()


def _fetch_authorized_domains(project_id: str, token: str) -> list[str]:
    url = IDENTITY_TOOLKIT_CONFIG_URL.format(project_id=project_id)
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": project_id,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            body = json.load(response)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(
            f"ERROR: Identity Toolkit config fetch failed ({e.code}): {detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: could not reach Identity Toolkit API: {e}", file=sys.stderr)
        sys.exit(1)
    return list(body.get("authorizedDomains", []))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id", required=True, help="Firebase project ID, e.g. warmer-prod-260813"
    )
    parser.add_argument(
        "--domain",
        action="append",
        required=True,
        dest="domains",
        help="Domain that must be authorized. Repeat for multiple domains.",
    )
    args = parser.parse_args(argv)

    token = _access_token()
    authorized = _fetch_authorized_domains(args.project_id, token)
    missing = [d for d in args.domains if d not in authorized]

    if not missing:
        print(
            f"OK: all of {args.domains} are in {args.project_id}'s authorizedDomains {authorized}"
        )
        return

    remediation = json.dumps({"authorizedDomains": sorted(set(authorized) | set(missing))})
    print(
        f"ERROR: {missing} NOT in {args.project_id}'s authorizedDomains {authorized}. "
        "Every firebase_auth call (including anonymous sign-in) from an unauthorized "
        "origin fails with a misleading '[firebase_auth/channel-error]' at runtime -- "
        "see the 2026-07-07 incident note in docs/firebase-setup.md.\n\n"
        "Fix -- one-line remediation:\n"
        "  TOKEN=$(gcloud auth print-access-token)\n"
        "  curl -X PATCH \\\n"
        '    -H "Authorization: Bearer $TOKEN" \\\n'
        f'    -H "x-goog-user-project: {args.project_id}" \\\n'
        '    -H "Content-Type: application/json" \\\n'
        f'    "{IDENTITY_TOOLKIT_CONFIG_URL.format(project_id=args.project_id)}'
        '?updateMask=authorizedDomains" \\\n'
        f"    -d '{remediation}'",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
