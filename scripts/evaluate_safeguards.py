"""Measure answer-policy abstention trade-offs on authored development cases."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path

from app.cache.answer_policy import AnswerPolicy
from app.cache.verifier import NliVerifier

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation" / "dev" / "safeguard_cases_v1.tsv"
ARTIFACT = ROOT / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
RUNS = ROOT / "evaluation" / "runs"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(run_id: str) -> Path:
    if not run_id.isidentifier():
        raise ValueError("run_id must be an identifier")
    target = RUNS / run_id
    target.mkdir(parents=True, exist_ok=False)
    policy = AnswerPolicy.load(ARTIFACT)
    verifier = NliVerifier()
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    if len({case["pair_id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate development pair ID")
    decisions = []
    for case in cases:
        decision = policy.decide(
            case["incoming_query"],
            case["cached_query"],
            case["cached_answer"],
            0.95,  # isolate the answer policy after retrieval
            verifier,
        )
        decisions.append(
            {
                **case,
                "label_type": "authored_development",
                "action": decision.action,
                "reason": decision.reason,
                "nli_score": decision.score,
            }
        )
    if verifier.unavailable:
        raise RuntimeError("Pinned NLI verifier unavailable")
    with (target / "decisions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(decisions[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(decisions)
    summary = {
        "n": len(decisions),
        "valid_n": sum(row["reuse_ok"] == "true" for row in decisions),
        "unsafe_n": sum(row["reuse_ok"] == "false" for row in decisions),
        "valid_accepted": sum(
            row["reuse_ok"] == "true" and row["action"] == "ACCEPT" for row in decisions
        ),
        "lost_valid_reuse": sum(
            row["reuse_ok"] == "true" and row["action"] != "ACCEPT" for row in decisions
        ),
        "unsafe_accepted": sum(
            row["reuse_ok"] == "false" and row["action"] == "ACCEPT" for row in decisions
        ),
        "unsafe_declined": sum(
            row["reuse_ok"] == "false" and row["action"] != "ACCEPT" for row in decisions
        ),
        "nli_scored": sum(row["nli_score"] is not None for row in decisions),
        "by_category": {},
    }
    for category in sorted({str(row["category"]) for row in decisions}):
        group = [row for row in decisions if row["category"] == category]
        summary["by_category"][category] = {
            "n": len(group),
            "valid_accepted": sum(
                row["reuse_ok"] == "true" and row["action"] == "ACCEPT" for row in group
            ),
            "valid_declined": sum(
                row["reuse_ok"] == "true" and row["action"] != "ACCEPT" for row in group
            ),
            "unsafe_accepted": sum(
                row["reuse_ok"] == "false" and row["action"] == "ACCEPT" for row in group
            ),
        }
    (target / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "safeguard-development-v1",
        "run_id": run_id,
        "label_type": "authored_development",
        "input_sha256": _sha(SOURCE),
        "policy_artifact_sha256": _sha(ARTIFACT),
        "policy_source_sha256": _sha(ROOT / "app" / "cache" / "answer_policy.py"),
        "verifier_source_sha256": _sha(ROOT / "app" / "cache" / "verifier.py"),
        "python": platform.python_version(),
        "outputs": {name: _sha(target / name) for name in ("decisions.csv", "summary.json")},
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    print(run(parser.parse_args().run_id))
