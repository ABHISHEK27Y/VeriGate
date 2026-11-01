"""Convert pytest's JUnit XML counts into a small reviewable JSON artifact."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results"


def main() -> None:
    source = RESULTS / "tests.xml"
    root = ET.parse(source).getroot()  # noqa: S314 - locally generated pytest XML
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("No pytest test suites found")
    totals = {
        key: sum(int(suite.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    if min(totals.values()) < 0:
        raise ValueError("Invalid pytest test counts")
    (RESULTS / "checks.json").write_text(
        json.dumps(totals, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(totals)


if __name__ == "__main__":
    main()
