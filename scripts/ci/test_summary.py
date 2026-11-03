"""Turn a test report into pass/fail/skip counts for the GitHub job summary.

Two inputs:
  junit   -- pytest's --junitxml file (generator)
  flutter -- `flutter test --file-reporter json:<path>` output (app)

Writes a markdown table to $GITHUB_STEP_SUMMARY when set, and a JSON counts file.
The job summary is the citable source for README test counts: a count without a
CI run behind it is a local number, not a provenance-backed one.

Fails closed: a missing, unparseable, or empty report exits non-zero, so a
broken test step can't produce a green "0 failed" summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = failed = skipped = 0
    for suite in suites:
        total += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0)) + int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
    passed = total - failed - skipped
    return {"passed": passed, "failed": failed, "skipped": skipped, "total": total}


def flutter_counts(path: Path) -> dict[str, int]:
    passed = failed = skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        # `hidden` marks the runner's synthetic "loading <file>" entries, not tests.
        if event.get("type") != "testDone" or event.get("hidden"):
            continue
        if event.get("skipped"):
            skipped += 1
        elif event.get("result") == "success":
            passed += 1
        else:
            failed += 1
    total = passed + failed + skipped
    return {"passed": passed, "failed": failed, "skipped": skipped, "total": total}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["junit", "flutter"])
    parser.add_argument("report", type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if not args.report.is_file():
        print(f"::error::{args.label}: report {args.report} not found", file=sys.stderr)
        return 1
    try:
        counts = junit_counts(args.report) if args.kind == "junit" else flutter_counts(args.report)
    except (ET.ParseError, OSError, ValueError) as exc:
        print(f"::error::{args.label}: could not parse {args.report}: {exc}", file=sys.stderr)
        return 1
    if counts["total"] == 0:
        print(f"::error::{args.label}: report {args.report} contains no tests", file=sys.stderr)
        return 1

    record = {
        "label": args.label,
        **counts,
        "commit": os.environ.get("GITHUB_SHA", "local"),
        "run_url": (
            f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
            if "GITHUB_RUN_ID" in os.environ
            else "local"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    table = (
        f"### {args.label} tests\n\n"
        "| passed | failed | skipped | total | commit |\n"
        "|---:|---:|---:|---:|---|\n"
        f"| {counts['passed']} | {counts['failed']} | {counts['skipped']} | {counts['total']} "
        f"| `{record['commit'][:7]}` |\n"
    )
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(table + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
