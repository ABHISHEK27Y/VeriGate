"""Run authored exploratory demo queries against a local mock semantic gateway.

Restores the designated demo tenant before every case and once at the end.
These labels are authored development checks, not independent accuracy evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation" / "dev" / "semantic_demo_probe_v1.tsv"
API_KEY = "demo-key-123"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(base_url: str, output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    rows = []
    with httpx.Client(base_url=base_url, timeout=30) as client:
        ready = client.get("/ready")
        ready.raise_for_status()
        config = ready.json()
        if not (
            config["cache_match_mode"] == "semantic"
            and config["embedding_backend"] == "minilm"
            and config["vector_backend"] == "redisearch"
            and config["answer_policy_version"]
            and config["answer_policy_prewarm"]
            and config["providers"] == ["mock"]
            and config["demo_restore_available"]
        ):
            raise RuntimeError("Probe requires the explicit, ready local mock semantic demo")
        headers = {"x-api-key": API_KEY}
        try:
            for case in cases:
                reset = client.post("/admin/demo/restore", headers=headers)
                reset.raise_for_status()
                started = time.perf_counter()
                response = client.post(
                    "/v1/chat", headers=headers, json={"prompt": case["incoming_query"]}
                )
                response.raise_for_status()
                body = response.json()
                expected = case["expected_reuse"] == "true"
                rows.append(
                    {
                        **case,
                        "cache": body["cache"],
                        "provider": body["provider"],
                        "answer": body["answer"],
                        "reason": body["note"],
                        "similarity": body["similarity"],
                        "gateway_ms": body["latency_ms"],
                        "http_ms": round((time.perf_counter() - started) * 1000, 3),
                        "outcome": (
                            "valid_reuse"
                            if expected and body["cache"] == "HIT"
                            else "lost_valid_reuse"
                            if expected
                            else "suspected_incorrect_accept"
                            if body["cache"] == "HIT"
                            else "unsafe_declined"
                        ),
                    }
                )
        finally:
            reset = client.post("/admin/demo/restore", headers=headers)
            reset.raise_for_status()
    with (output / "rows.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "schema_version": "semantic-demo-probe-v1",
        "label_type": "authored_exploratory",
        "input_sha256": _sha(SOURCE),
        "source_sha256": _sha(Path(__file__)),
        "policy_version": config["answer_policy_version"],
        "embedding_backend": config["embedding_backend"],
        "provider": "mock",
        "python": platform.python_version(),
        "rows_sha256": _sha(output / "rows.csv"),
        "counts": {
            name: sum(row["outcome"] == name for row in rows)
            for name in (
                "valid_reuse",
                "lost_valid_reuse",
                "suspected_incorrect_accept",
                "unsafe_declined",
            )
        },
        "fixtures_restored_after_run": True,
    }
    with (output / "manifest.json").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["counts"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    run(args.base_url, args.output)
