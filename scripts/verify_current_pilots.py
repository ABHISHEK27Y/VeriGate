"""Check pilot artifacts against frozen inputs and source at each run revision."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "evaluation" / "runs"
ARTIFACT = ROOT / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
PILOTS = (
    ("nq_dev_minilm_pilot_v3", ROOT / "evaluation" / "pilot_freeze_nq_dev_v1.json", "4870b1f"),
    ("nq_dev_close_neighbors_v2", ROOT / "evaluation" / "close_neighbor_freeze_v1.json", "4870b1f"),
    ("nq_dev_close_neighbors_v4", ROOT / "evaluation" / "close_neighbor_freeze_v1.json", None),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_sha(name: str, commit: str | None) -> str:
    if commit is None:
        return _sha(ROOT / name)
    source = subprocess.run(
        ["git", "show", f"{commit}:{name}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(source).hexdigest()


def verify() -> None:
    for run_id, freeze_path, source_commit in PILOTS:
        folder = RUNS / run_id
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        if manifest["run_id"] != run_id or manifest["freeze_sha256"] != _sha(freeze_path):
            raise ValueError(f"Pilot freeze mismatch: {run_id}")
        if manifest["source_sha256"] != freeze["source_sha256"]:
            raise ValueError(f"Pilot source declaration mismatch: {run_id}")
        artifact_digest = manifest.get("artifact_sha256") or manifest.get(
            "answer_policy_artifact_sha256"
        )
        if artifact_digest != _sha(ARTIFACT):
            raise ValueError(f"Pilot policy artifact changed: {run_id}")
        for name, digest in manifest["outputs"].items():
            if Path(name).name != name or _sha(folder / name) != digest:
                raise ValueError(f"Pilot output changed: {run_id}/{name}")
        for name, digest in manifest["source_code_sha256"].items():
            if _source_sha(name, source_commit) != digest:
                raise ValueError(f"Pilot implementation changed: {run_id}/{name}")
    print("verified committed NQ pilot manifests, outputs and recorded source hashes")


if __name__ == "__main__":
    verify()
