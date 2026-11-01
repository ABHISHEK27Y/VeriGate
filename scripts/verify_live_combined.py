"""Verify the frozen forward/reverse HTTP challenge and row-level counts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evaluation/runs/technical_combined_fresh_20261101_v1"
POLICY = ROOT / "app/cache/artifacts/answer_policy_v1.json"
VARIANTS = ("baseline", "combined")
RUNS = ("results_forward_verified", "results_reverse")
HTTP_OK = 200


def verify() -> None:
    freeze = json.loads((RUN / "freeze.json").read_text(encoding="utf-8"))
    workload = (RUN / "workload.json").read_bytes()
    assert hashlib.sha256(workload).hexdigest() == freeze["workload_sha256"]
    expected = [
        (family["family"], probe["question"], probe["label"])
        for family in json.loads(workload)
        for probe in family["probes"]
    ]
    assert len(expected) == freeze["probes"]
    evaluator_hash = hashlib.sha256(
        (ROOT / "scripts/evaluate_live_combined.py").read_bytes()
    ).hexdigest()
    policy_hash = hashlib.sha256(POLICY.read_bytes()).hexdigest()
    for name in RUNS:
        source = RUN / name
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["workload_sha256"] == freeze["workload_sha256"]
        assert manifest["source_sha256"] == evaluator_hash
        assert manifest["policy_sha256"] == policy_hash
        summary = json.loads((source / "summary.json").read_text(encoding="utf-8"))
        for variant in VARIANTS:
            rows = json.loads((source / variant / "rows.json").read_text(encoding="utf-8"))
            assert [(r["family"], r["query"], r["label"]) for r in rows] == expected
            assert all(r["http_status"] == HTTP_OK for r in rows)
            assert all(r["cache"] in {"HIT", "MISS"} for r in rows)
            assert manifest["startup"][variant]["readiness"]["answer_policy_prewarm"]
            assert manifest["startup"][variant]["readiness"]["cache_match_mode"] == "semantic"
            assert manifest["startup"][variant]["readiness"][
                "answer_policy_applicability_guard"
            ] is (variant == "combined")
            assert summary[variant]["valid_reuse"] == sum(
                r["valid_reuse"] for r in rows if r["label"] == "valid"
            )
            assert summary[variant]["invalid_accepts"] == sum(
                r["incorrect_accept"] for r in rows if r["label"] == "invalid"
            )
            assert summary[variant]["ambiguous_approvals"] == sum(
                r["cache"] == "HIT" for r in rows if r["label"] == "ambiguous"
            )
            assert summary[variant]["provider_calls"] == sum(
                r["provider_invoked"] is True for r in rows
            )
            assert summary[variant]["total_provider_fallbacks"] == sum(
                r["cache"] == "MISS" for r in rows
            )
            assert all(
                r["selected_cached_query"] in r["suitable_queries"]
                for r in rows
                if r["valid_reuse"]
            )
    print("Verified frozen 25-probe HTTP challenge in both startup orders")


if __name__ == "__main__":
    verify()
