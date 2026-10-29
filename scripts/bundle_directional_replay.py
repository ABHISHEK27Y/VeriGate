"""Produce one immutable local, hash-vector, concrete-answer replay bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from app.cache.namespace import POLICY_VERSION
from app.embeddings import active_backend
from evaluation.reproduce import ROOT
from evaluation.stream_gold import run

RUNS = ROOT / "evaluation" / "runs"
PAIR_FILE = ROOT / "data" / "answer_pairs_directional.tsv"
AUDIT = ROOT / "evaluation" / "results" / "answer_label_audit.json"
SOURCE_FILES = (
    "app/cache/policy.py",
    "app/cache/verifier.py",
    "app/cache/namespace.py",
    "evaluation/gold_answers.py",
    "evaluation/stream.py",
    "evaluation/stream_gold.py",
    "scripts/bundle_directional_replay.py",
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(run_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{3,63}", run_id):
        raise ValueError("run_id must use 4–64 lowercase ASCII letters, digits, - or _")
    if active_backend() != "hash":
        raise ValueError("This bundle requires EMBEDDING_BACKEND=hash")
    target = RUNS / run_id
    if target.exists():
        raise FileExistsError(f"Immutable run already exists: {target}")
    target.mkdir(parents=True)
    started = time.perf_counter()
    replay_path = run(target / "directional_stream_hash.csv")
    elapsed = time.perf_counter() - started
    shutil.copy2(AUDIT, target / AUDIT.name)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    manifest = {
        "schema_version": "directional-replay-bundle-v1",
        "run_id": run_id,
        "git_head_before_run": revision,
        "dirty_source_sha256": {name: _hash(ROOT / name) for name in SOURCE_FILES},
        "input": {
            "path": "data/answer_pairs_directional.tsv",
            "sha256": _hash(PAIR_FILE),
            "label_type": "cached_answer_reference_match",
            "source": "NQ-open historical pair selection; directional reference-string relabel",
        },
        "policy_version": POLICY_VERSION,
        "embedding_backend": "hash",
        "request_count": 1500,
        "seed": 11,
        "capacity_per_tenant": [10, 100],
        "ttl_steps": 500,
        "tenant_count": 3,
        "command": f"EMBEDDING_BACKEND=hash python -m scripts.bundle_directional_replay {run_id}",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "elapsed_seconds_including_plot": elapsed,
        "artifacts_sha256": {
            replay_path.name: _hash(replay_path),
            replay_path.with_suffix(".png").name: _hash(replay_path.with_suffix(".png")),
            AUDIT.name: _hash(target / AUDIT.name),
        },
        "limit": "Mocked reference responses and lexical vectors; no provider cost or answer truth",
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    args = parser.parse_args()
    print(bundle(args.run_id))


if __name__ == "__main__":
    main()
