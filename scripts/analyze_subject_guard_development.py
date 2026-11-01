"""Save per-position comparison for the inspected song development workload."""

from __future__ import annotations

import csv
import json
from collections import Counter

from scripts.stress_semantic_http import ROOT, digest, write_csv

OLD = ROOT / "evaluation/runs/nq_song_stress_20261030_v3/answer_aware_sufficient/requests.csv"
NEW = (
    ROOT
    / "evaluation/runs/nq_song_guard_development_20261030_v1/answer_aware_sufficient/requests.csv"
)
OUTPUT = ROOT / "evaluation/runs/nq_song_guard_development_20261030_v1"
EXPECTED_ROWS = 1000


def analyze() -> None:
    with OLD.open(encoding="utf-8", newline="") as stream:
        old = {row["id"]: row for row in csv.DictReader(stream)}
    with NEW.open(encoding="utf-8", newline="") as stream:
        new = {row["id"]: row for row in csv.DictReader(stream)}
    if len(old) != EXPECTED_ROWS or old.keys() != new.keys():
        raise ValueError("Incomplete or mismatched frozen development runs")
    rows = [
        {
            "id": identifier,
            "old_outcome": prior["outcome"],
            "guarded_outcome": new[identifier]["outcome"],
            "old_cached_query": prior["selected_cached_query"],
            "guarded_cached_query": new[identifier]["selected_cached_query"],
            "guarded_reason": new[identifier]["reason"],
        }
        for identifier, prior in old.items()
    ]
    write_csv(OUTPUT / "position_comparison.csv", rows)
    transitions = Counter((row["old_outcome"], row["guarded_outcome"]) for row in rows)
    (OUTPUT / "position_comparison_manifest.json").write_text(
        json.dumps(
            {
                "old_requests_sha256": digest(OLD),
                "guarded_requests_sha256": digest(NEW),
                "comparison_sha256": digest(OUTPUT / "position_comparison.csv"),
                "transitions": [
                    {"old": old_status, "guarded": new_status, "count": count}
                    for (old_status, new_status), count in sorted(transitions.items())
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    analyze()
