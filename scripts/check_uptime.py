"""Fail loudly if the live app, the CDN manifest, or a real CDN payload is
unreachable or malformed — guards against the 2026-07-12 incident class.

Background: the `playwarmer` Vercel project was deleted from the account
(cause unknown) and both production domains 404'd for an unknown window
before anyone noticed — nothing alerted, it was found by accident during an
unrelated deploy. This script is the fix: a cheap, dependency-free check
runnable both on a schedule (see .github/workflows/uptime-check.yml, which
opens a GitHub issue on failure) and by hand after any deploy.

Three checks, each independently informative about a different failure mode:
  1. APP    — the Vercel-hosted Flutter shell (catches: deleted/misconfigured
              Vercel project, DNS/alias breakage, a non-200 or wrong page).
  2. CDN    — the GitHub Pages payloads manifest (catches: Pages build
              failure, repo/branch misconfiguration).
  3. PAYLOAD — one real day file referenced BY that manifest (catches: Pages
              serving stale/empty content with a healthy-looking 200, or a
              manifest that lists files that were never actually published).

Deliberately stdlib-only (urllib, gzip, json) so it needs no environment
setup beyond a Python 3 interpreter — same convention as the other
scripts/check_*.py guards in this repo.

Usage:
    python scripts/check_uptime.py
    python scripts/check_uptime.py --app-url https://playwarmer.vercel.app/
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_APP_URL = "https://playwarmer.vercel.app/"
DEFAULT_MANIFEST_URL = "https://gaurav-gandhi-2411.github.io/mindmeld-payloads/manifest.json"
DEFAULT_CDN_BASE = "https://gaurav-gandhi-2411.github.io/mindmeld-payloads/"

TIMEOUT_S = 15
# String that must appear in the app shell's HTML — catches a 200 that is
# actually Vercel's default/placeholder page rather than our own index.html.
APP_SIGNATURE = "Warmer"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "warmer-uptime-check/1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310
        return resp.status, resp.read()


def check_app(url: str) -> CheckResult:
    try:
        status, body = _get(url)
    except urllib.error.HTTPError as exc:
        return CheckResult("app", False, f"HTTP {exc.code} fetching {url}")
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckResult("app", False, f"unreachable: {url} ({exc})")

    if status != 200:
        return CheckResult("app", False, f"HTTP {status} fetching {url}")
    text = body.decode("utf-8", errors="replace")
    if APP_SIGNATURE not in text:
        return CheckResult(
            "app", False, f"200 but signature {APP_SIGNATURE!r} not found in body — "
            "likely a placeholder/wrong-project page, not the real app"
        )
    return CheckResult("app", True, f"200, signature present ({url})")


def check_manifest(url: str) -> CheckResult:
    try:
        status, body = _get(url)
    except urllib.error.HTTPError as exc:
        return CheckResult("cdn_manifest", False, f"HTTP {exc.code} fetching {url}")
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckResult("cdn_manifest", False, f"unreachable: {url} ({exc})")

    if status != 200:
        return CheckResult("cdn_manifest", False, f"HTTP {status} fetching {url}")
    try:
        manifest = json.loads(body)
    except json.JSONDecodeError as exc:
        return CheckResult("cdn_manifest", False, f"200 but invalid JSON: {exc}")

    langs = manifest.get("langs", {})
    if not langs or "en" not in langs or not langs["en"].get("days"):
        return CheckResult("cdn_manifest", False, "manifest has no en.days entries")
    return CheckResult(
        "cdn_manifest", True, f"200, valid JSON, {len(langs['en']['days'])} en day(s) listed"
    )


def check_payload(cdn_base: str, manifest_url: str) -> CheckResult:
    try:
        _, manifest_body = _get(manifest_url)
        manifest = json.loads(manifest_body)
        first_file = manifest["langs"]["en"]["days"][0]["file"]
    except Exception as exc:  # noqa: BLE001 - any failure here means "can't even pick a target"
        return CheckResult("cdn_payload", False, f"could not determine a payload to check: {exc}")

    payload_url = cdn_base.rstrip("/") + "/" + first_file
    try:
        status, body = _get(payload_url)
    except urllib.error.HTTPError as exc:
        return CheckResult("cdn_payload", False, f"HTTP {exc.code} fetching {payload_url}")
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckResult("cdn_payload", False, f"unreachable: {payload_url} ({exc})")

    if status != 200:
        return CheckResult("cdn_payload", False, f"HTTP {status} fetching {payload_url}")
    try:
        payload = json.loads(gzip.decompress(body))
    except Exception as exc:  # noqa: BLE001 - gzip/json errors both mean "malformed payload"
        return CheckResult("cdn_payload", False, f"200 but could not decode gzip+JSON: {exc}")

    required = {"date", "words", "maxGuesses", "salt"}
    missing = required - payload.keys()
    if missing:
        return CheckResult("cdn_payload", False, f"payload missing keys: {sorted(missing)}")
    return CheckResult(
        "cdn_payload", True, f"200, valid gzip+JSON, {len(payload['words'])} words ({payload_url})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", default=DEFAULT_APP_URL)
    parser.add_argument("--manifest-url", default=DEFAULT_MANIFEST_URL)
    parser.add_argument("--cdn-base", default=DEFAULT_CDN_BASE)
    args = parser.parse_args(argv)

    results = [
        check_app(args.app_url),
        check_manifest(args.manifest_url),
        check_payload(args.cdn_base, args.manifest_url),
    ]

    for r in results:
        mark = "OK  " if r.ok else "FAIL"
        print(f"[{mark}] {r.name}: {r.detail}")

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\n{len(failed)}/{len(results)} check(s) FAILED.")
        return 1
    print(f"\nAll {len(results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
