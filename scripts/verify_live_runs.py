"""Validate the saved live CI runs without regenerating or retuning them."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = (
    ("real_semantic_38d021e_v1", "scripts/benchmark_real_semantic.py"),
    ("multiworker_38d021e_v1", "scripts/test_multiworker_redis.py"),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> None:
    for run_id, source in RUNS:
        folder = ROOT / "evaluation" / "runs" / run_id
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if manifest["source_code_sha256"] != _sha(ROOT / source):
            raise ValueError(f"Source code changed since live run: {run_id}")
        for name, expected in manifest["outputs"].items():
            if Path(name).name != name or _sha(folder / name) != expected:
                raise ValueError(f"Live run output changed: {run_id}/{name}")
    print("verified saved real-semantic and two-worker CI run hashes")


if __name__ == "__main__":
    verify()
