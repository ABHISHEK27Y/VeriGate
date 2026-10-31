"""Validate an immutable replay bundle before using its numbers in a report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import cast

from app.cache.namespace import POLICY_VERSION
from scripts.bundle_directional_replay import RUNS, SOURCE_FILES, _hash

REQUIRED = {
    "capacity_per_tenant",
    "system",
    "requests",
    "accepted_known",
    "accepted_known_false",
    "label_type",
    "embedding_backend",
}
EXPECTED_ROWS = 6


def verify(  # noqa: PLR0912 - each independent integrity check fails closed
    path: Path, *, require_current_source: bool = False
) -> dict[str, object]:
    root = path.resolve()
    if root.parent != RUNS.resolve():
        raise ValueError("Bundle must be an immediate child of evaluation/runs")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != "directional-replay-bundle-v1":
        raise ValueError("Incompatible bundle schema")
    if manifest["run_id"] != root.name or manifest["policy_version"] != POLICY_VERSION:
        raise ValueError("Run or policy version mismatch")
    if manifest["input"]["label_type"] != "cached_answer_reference_match":
        raise ValueError("Incompatible input label")
    for name, expected in manifest["artifacts_sha256"].items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("Invalid artifact name")
        if _hash(root / name) != expected:
            raise ValueError(f"Artifact hash mismatch: {name}")
    csv_path = root / "directional_stream_hash.csv"
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError("Replay CSV schema mismatch")
        rows = list(reader)
    if len(rows) != EXPECTED_ROWS:
        raise ValueError("Expected two capacities and three systems")
    if any(
        row["label_type"] != "cached_answer_reference_match_replay"
        or row["embedding_backend"] != "hash"
        or int(row["requests"]) != manifest["request_count"]
        or int(row["accepted_known_false"]) > int(row["accepted_known"])
        for row in rows
    ):
        raise ValueError("Incompatible or malformed replay result")
    if require_current_source:
        if _hash(RUNS.parents[1] / manifest["input"]["path"]) != manifest["input"]["sha256"]:
            raise ValueError("Current input differs from run")
        for name in SOURCE_FILES:
            if _hash(RUNS.parents[1] / name) != manifest["dirty_source_sha256"][name]:
                raise ValueError(f"Current source differs from run: {name}")
    return cast("dict[str, object]", manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--require-current-source", action="store_true")
    args = parser.parse_args()
    manifest = verify(RUNS / args.run_id, require_current_source=args.require_current_source)
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    print(f"verified {args.run_id} manifest {digest}")


if __name__ == "__main__":
    main()
