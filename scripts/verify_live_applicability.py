"""Validate the frozen live gateway comparison and its row-level evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.analyze_live_applicability import analyze

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evaluation/runs/technical_applicability_live_20261101_v1"
VARIANTS = ("applicability_off", "applicability_on")
HTTP_OK = 200


def verify() -> None:
    freeze = json.loads((RUN / "freeze.json").read_text(encoding="utf-8"))
    source = (RUN / "workload.json").read_bytes()
    assert hashlib.sha256(source).hexdigest() == freeze["workload_sha256"]
    workload = json.loads(source)
    expected = [
        (family["family"], probe["question"], probe["label"])
        for family in workload
        for probe in family["probes"]
    ]
    results = RUN / "results_complete"
    manifest = json.loads((results / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["workload_sha256"] == freeze["workload_sha256"]
    assert (
        manifest["policy_sha256"]
        == hashlib.sha256((ROOT / freeze["policy_artifact"]).read_bytes()).hexdigest()
    )
    assert (
        manifest["source_sha256"]
        == hashlib.sha256(
            (ROOT / "scripts/evaluate_live_applicability.py").read_bytes()
        ).hexdigest()
    )
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    trace_analysis = json.loads((results / "trace_analysis.json").read_text(encoding="utf-8"))
    assert trace_analysis == analyze()
    for variant in VARIANTS:
        rows = json.loads((results / variant / "rows.json").read_text(encoding="utf-8"))
        assert len(rows) == len(expected) == freeze["probes"]
        assert [(row["family"], row["query"], row["label"]) for row in rows] == expected
        assert all(row["http_status"] == HTTP_OK for row in rows)
        assert all(row["candidate_count"] == freeze["candidate_count_per_probe"] for row in rows)
        assert all(
            len(row["candidate_trace"]) == freeze["candidate_count_per_probe"] for row in rows
        )
        assert all(row["cache"] in {"HIT", "MISS"} for row in rows)
        assert manifest["startup"][variant]["readiness"]["answer_policy_applicability_guard"] is (
            variant == "applicability_on"
        )
        measured = summary[variant]
        assert measured["valid_reuse"] == sum(
            row["valid_reuse"] for row in rows if row["label"] == "valid"
        )
        assert measured["provider_calls"] == sum(row["provider_invoked"] for row in rows)
        assert (
            measured["verification_abstentions"]
            == trace_analysis[variant]["misses_after_candidate_assessment"]
        )
    print("Verified 50 paired live HTTP/RedisSearch observations")


if __name__ == "__main__":
    verify()
