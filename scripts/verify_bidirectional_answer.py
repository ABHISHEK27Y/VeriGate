"""Check the frozen technical lockbox and saved row-level results without rerunning models."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evaluation/runs/technical_bidirectional_lockbox_20261101_v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> None:  # noqa: PLR0912 - explicit artifact integrity checks
    freeze = json.loads((RUN / "freeze.json").read_text(encoding="utf-8"))
    manifest = json.loads((RUN / "results_timed/manifest.json").read_text(encoding="utf-8"))
    workload = json.loads((RUN / "workload.json").read_text(encoding="utf-8"))
    if digest(RUN / "workload.json") != freeze["workload_sha256"]:
        raise ValueError("Frozen workload changed")
    if (
        digest(ROOT / "app/cache/artifacts/answer_policy_v1.json")
        != freeze["policy_artifact_sha256"]
    ):
        raise ValueError("Pinned policy changed")
    if manifest["workload_sha256"] != freeze["workload_sha256"]:
        raise ValueError("Result input differs from frozen workload")
    if digest(ROOT / manifest["source"]) != manifest["source_sha256"]:
        raise ValueError("Evaluation source changed")
    for name, expected in manifest["outputs"].items():
        if Path(name).name != name or digest(RUN / "results_timed" / name) != expected:
            raise ValueError(f"Saved result changed: {name}")
    with (RUN / "results_timed/decisions.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(workload) != freeze["families"] or len(rows) != freeze["cases"] * len(
        freeze["variants"]
    ):
        raise ValueError("Frozen family or result count changed")
    summary = json.loads((RUN / "results_timed/summary.json").read_text(encoding="utf-8"))
    for variant in freeze["variants"]:
        subset = [row for row in rows if row["variant"] == variant]
        if len(subset) != freeze["cases"]:
            raise ValueError("Incomplete variant")
        for label, expected in freeze["labels"].items():
            labelled = [row for row in subset if row["label"] == label]
            if len(labelled) != expected or any(not row["contract"] for row in labelled):
                raise ValueError("Missing independent label or contract")
        counts = summary["variants"][variant]
        for label, key in (
            ("valid", "valid_reuse"),
            ("invalid", "invalid_accepts"),
            ("abstain", "ambiguous_accepts"),
        ):
            observed = sum(row["label"] == label and row["action"] == "ACCEPT" for row in subset)
            if observed != counts[key]:
                raise ValueError(f"Incorrect {variant} {key}")
    print("verified frozen technical lockbox and 60 saved variant decisions")


if __name__ == "__main__":
    verify()
