"""Save a bounded authored development check of conservative cache bypasses."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from app.cache.volatility import is_volatile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation" / "dev" / "freshness_cases_v1.tsv"
POLICY = ROOT / "app" / "cache" / "volatility.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(run_id: str) -> Path:
    if not run_id.isidentifier():
        raise ValueError("run_id must be an identifier")
    output = ROOT / "evaluation" / "runs" / run_id
    output.mkdir(parents=True, exist_ok=False)
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    rows = [
        {
            **case,
            "bypass": is_volatile(case["query"]),
            "label_type": "authored_development",
        }
        for case in cases
    ]
    with (output / "decisions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "n": len(rows),
        "stable_n": sum(row["volatile"] == "false" for row in rows),
        "volatile_n": sum(row["volatile"] == "true" for row in rows),
        "stable_bypassed": sum(
            row["volatile"] == "false" and row["bypass"] is True for row in rows
        ),
        "volatile_bypassed": sum(
            row["volatile"] == "true" and row["bypass"] is True for row in rows
        ),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "freshness-development-v1",
        "run_id": run_id,
        "label_type": "authored_development",
        "input_sha256": _sha(SOURCE),
        "policy_source_sha256": _sha(POLICY),
        "outputs": {name: _sha(output / name) for name in ("decisions.csv", "summary.json")},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    print(run(parser.parse_args().run_id))
