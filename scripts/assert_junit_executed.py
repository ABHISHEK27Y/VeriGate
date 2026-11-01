"""Fail CI when a required opt-in test silently skips instead of running.

Opt-in regressions (the pinned-NLI transformation contract and the Playwright
dashboard regression) are gated behind environment flags and a model/browser
download. A plain ``pytest`` invocation reports success even when every such
test is skipped, so a job that merely *invokes* them proves nothing. This script
parses the JUnit XML those jobs emit and fails unless the required tests actually
executed: at least ``--min-passed`` passed, and zero skipped, failed or errored.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path


def summarize(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()  # noqa: S314 - locally generated pytest XML
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError(f"No pytest test suites found in {path}")
    return {
        key: sum(int(suite.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path, help="pytest --junitxml output to inspect")
    parser.add_argument(
        "--min-passed",
        type=int,
        default=1,
        help="minimum number of tests that must have passed (executed and succeeded)",
    )
    args = parser.parse_args(argv)

    totals = summarize(args.junit)
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    problems = []
    if totals["skipped"]:
        problems.append(f"{totals['skipped']} skipped (required test did not execute)")
    if totals["failures"] or totals["errors"]:
        problems.append(f"{totals['failures']} failed, {totals['errors']} errored")
    if passed < args.min_passed:
        problems.append(f"only {passed} passed, expected at least {args.min_passed}")
    if problems:
        print(f"FAIL {args.junit}: " + "; ".join(problems), file=sys.stderr)
        print(f"  totals={totals} passed={passed}", file=sys.stderr)
        return 1
    print(f"OK {args.junit}: {passed} passed, 0 skipped, 0 failures, 0 errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
