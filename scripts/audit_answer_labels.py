"""Audit old symmetric NQ labels and prepare an unreviewed directional review set.

The output is local under gitignored data/. Only aggregate counts are tracked.
No string mismatch is automatically declared a wrong answer.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

from evaluation.gold_answers import cached_answer_reference_match

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "gold_answer_pairs.tsv"
DISCREPANCIES = ROOT / "data" / "answer_label_discrepancies.tsv"
REVIEW = ROOT / "data" / "answer_review_directional.tsv"
SUMMARY = ROOT / "evaluation" / "results" / "answer_label_audit.json"
SEED = 20261029


def _write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    if path.exists():
        raise FileExistsError(f"Preserving existing review work: {path}")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(source: Path = SOURCE) -> dict[str, object]:
    with source.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows:
        raise ValueError("Empty source")
    rng = random.Random(SEED)
    mismatches = []
    positive: list[dict[str, str]] = []
    negative: list[dict[str, str]] = []
    for row in rows:
        incoming = json.loads(row["incoming_aliases"])
        if not isinstance(incoming, list):
            raise TypeError("Incoming answers must be a list")
        match = cached_answer_reference_match(row["cached_answer"], incoming)
        audited = {
            **row,
            "actual_answer_reference_match": str(int(match)),
            "reason_code": "cached_text_absent_from_incoming_references" if not match else "",
            "review_decision": "",
            "review_reason": "",
            "reviewer_1": "",
            "reviewer_2": "",
            "review_status": "unreviewed",
        }
        if row["reuse_ok"] == "1" and not match:
            mismatches.append(audited)
        (positive if row["reuse_ok"] == "1" else negative).append(audited)
    fields = list(rows[0]) + [
        "actual_answer_reference_match",
        "reason_code",
        "review_decision",
        "review_reason",
        "reviewer_1",
        "reviewer_2",
        "review_status",
    ]
    _write_tsv(DISCREPANCIES, fields, mismatches)
    # Diagnostic selection is intentionally enriched for discrepant and hard-negative cases.
    # The separate random subset is the only part suitable for prevalence estimates after review.
    diagnostic = rng.sample(mismatches, min(100, len(mismatches)))
    diagnostic += rng.sample(negative, min(100, len(negative)))
    random_sample = rng.sample(rows, min(150, len(rows)))
    review_rows = [dict(row, review_subset="diagnostic") for row in diagnostic]
    review_rows += [
        dict(
            {
                **row,
                "actual_answer_reference_match": str(
                    int(
                        cached_answer_reference_match(
                            row["cached_answer"], json.loads(row["incoming_aliases"])
                        )
                    )
                ),
                "reason_code": "",
                "review_decision": "",
                "review_reason": "",
                "reviewer_1": "",
                "reviewer_2": "",
                "review_status": "unreviewed",
            },
            review_subset="random",
        )
        for row in random_sample
    ]
    _write_tsv(REVIEW, [*fields, "review_subset"], review_rows)
    summary: dict[str, object] = {
        "schema_version": "answer-label-audit-v1",
        "source": "NQ-open historical gold_answer_match proxy",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "selection_seed": SEED,
        "rows": len(rows),
        "historical_positive_rows": len(positive),
        "historical_positive_cached_text_absent": len(mismatches),
        "review_diagnostic_rows": len(diagnostic),
        "review_random_rows": len(random_sample),
        "label_meaning": "reference-string membership only; actual reuse needs human review",
        "review_status": "unreviewed",
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
