"""Validate the frozen applicability workload and saved decisions."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evaluation/runs/technical_applicability_lockbox_20261101_v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> None:  # noqa: PLR0912 - explicit artifact checks
    freeze = json.loads((RUN / "freeze.json").read_text(encoding="utf-8"))
    manifest = json.loads((RUN / "results/manifest.json").read_text(encoding="utf-8"))
    if digest(RUN / "workload.json") != freeze["workload_sha256"]:
        raise ValueError("Frozen applicability workload changed")
    if (
        digest(ROOT / "app/cache/artifacts/answer_policy_v1.json")
        != freeze["policy_artifact_sha256"]
    ):
        raise ValueError("Answer-policy artifact changed")
    if manifest["workload_sha256"] != freeze["workload_sha256"]:
        raise ValueError("Results do not match frozen input")
    evaluator = ROOT / "scripts/evaluate_applicability.py"
    if digest(evaluator) != manifest["evaluation_source_sha256"]:
        raise ValueError("Historical evaluator changed")
    # The guard is under active development. Validate the original saved run
    # against the guard bytes at its frozen commit, never against today's code.
    old_guard = subprocess.run(  # noqa: S603 - fixed git executable and path
        [
            "git",
            "-C",
            str(ROOT),
            "show",
            f"{manifest['frozen_input_commit']}:app/cache/applicability.py",
        ],
        check=True,
        capture_output=True,
    ).stdout
    if hashlib.sha256(old_guard).hexdigest() != manifest["experimental_guard_sha256"]:
        raise ValueError("Frozen historical guard source changed")
    for name, expected in manifest["outputs"].items():
        if Path(name).name != name or digest(RUN / "results" / name) != expected:
            raise ValueError(f"Saved result changed: {name}")
    with (RUN / "results/decisions.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != freeze["cases"] * len(freeze["variants"]):
        raise ValueError("Incomplete decisions")
    summary = json.loads((RUN / "results/summary.json").read_text(encoding="utf-8"))
    for variant in freeze["variants"]:
        subset = [row for row in rows if row["variant"] == variant]
        if len(subset) != freeze["cases"]:
            raise ValueError("Incomplete variant")
        for label, expected in freeze["labels"].items():
            labelled = [row for row in subset if row["label"] == label]
            if len(labelled) != expected or any(not row["contract"] for row in labelled):
                raise ValueError("Missing controlled label or contract")
        for label, key in (
            ("valid", "valid_reuse"),
            ("invalid", "invalid_accepts"),
            ("abstain", "ambiguous_accepts"),
        ):
            observed = sum(row["label"] == label and row["action"] == "ACCEPT" for row in subset)
            if observed != summary["variants"][variant][key]:
                raise ValueError(f"Incorrect {variant} {key}")
    print("verified frozen applicability workload and 64 saved decisions")


if __name__ == "__main__":
    verify()
