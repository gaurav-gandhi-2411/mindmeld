"""Fail if the generator's blocklist differs from mindmeld-payloads' ci/blocklist.txt.

The payloads repo validates every published payload against ci/blocklist.txt, which is
generated from this repo's blocklist (profanity.load_en_profanity | load_hi_profanity).
If the two drift, payloads CI checks against a different list than the generator
filters with: a word added here would never be enforced there, or a word removed here
would make a correct build fail there. This compares the two as sets on every run.

Fails closed: if the payloads file can't be fetched or is empty, the check fails.
Prints counts and at most a few differing entries.
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PAYLOADS_BLOCKLIST_URL = (
    "https://raw.githubusercontent.com/gaurav-gandhi-2411/mindmeld-payloads/main/ci/blocklist.txt"
)
GENERATOR_DIR = Path(__file__).resolve().parents[2] / "generator"
MAX_SHOWN = 10


def fetch_payloads_blocklist() -> set[str]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(PAYLOADS_BLOCKLIST_URL, timeout=20) as resp:  # noqa: S310
                text = resp.read().decode("utf-8")
            # Same parsing as mindmeld-payloads ci/validate_payloads.py load_blocklist().
            return {
                ln.strip().lower()
                for ln in text.splitlines()
                if ln.strip() and not ln.startswith("#")
            }
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not fetch {PAYLOADS_BLOCKLIST_URL}: {last_error}")


def generator_blocklist() -> set[str]:
    sys.path.insert(0, str(GENERATOR_DIR))
    from profanity import load_en_profanity, load_hi_profanity

    return set(load_en_profanity() | load_hi_profanity())


def main() -> int:
    try:
        published = fetch_payloads_blocklist()
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if not published:
        print("::error::mindmeld-payloads ci/blocklist.txt has no entries", file=sys.stderr)
        return 1
    local = generator_blocklist()
    only_local = sorted(local - published)
    only_published = sorted(published - local)
    print(f"generator: {len(local)} entries; mindmeld-payloads main: {len(published)} entries")
    if not only_local and not only_published:
        print("blocklists match")
        return 0
    print(
        f"::error::blocklist drift: {len(only_local)} only in the generator, "
        f"{len(only_published)} only in mindmeld-payloads ci/blocklist.txt. "
        "Regenerate ci/blocklist.txt from the generator.",
        file=sys.stderr,
    )
    print(f"only in generator (first {MAX_SHOWN}): {only_local[:MAX_SHOWN]}")
    print(f"only in payloads (first {MAX_SHOWN}): {only_published[:MAX_SHOWN]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
