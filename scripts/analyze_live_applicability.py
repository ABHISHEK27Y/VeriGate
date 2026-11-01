"""Derive conservative request-level abstentions from saved candidate traces."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/runs/technical_applicability_live_20261101_v1/results_complete"


def analyze() -> dict[str, dict[str, int]]:
    result = {}
    for variant in ("applicability_off", "applicability_on"):
        rows = json.loads((RESULTS / variant / "rows.json").read_text(encoding="utf-8"))
        result[variant] = {
            "request_abstentions": sum(
                row["cache"] == "MISS"
                and (
                    any(candidate["action"] == "VERIFY" for candidate in row["candidate_trace"])
                    or row["reason"]
                    in {"verification_budget_exhausted", "conflicting_accepted_answers"}
                )
                for row in rows
            ),
            "misses_after_candidate_assessment": sum(
                row["cache"] == "MISS" and bool(row["candidate_trace"]) for row in rows
            ),
            "candidate_nli_scores": sum(
                candidate["verifier_status"] == "scored"
                for row in rows
                for candidate in row["candidate_trace"]
            ),
            "candidate_applicability_decisions": sum(
                candidate["reason"].startswith("applicability_")
                for row in rows
                for candidate in row["candidate_trace"]
            ),
        }
    return result


if __name__ == "__main__":
    (RESULTS / "trace_analysis.json").write_text(
        json.dumps(analyze(), indent=2) + "\n", encoding="utf-8"
    )
