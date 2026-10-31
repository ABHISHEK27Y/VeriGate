"""Audit every suspected false accept in the frozen song stress run."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.cache.answer_policy import AnswerPolicy, _scope_terms
from app.cache.subject_identity import named_work
from app.cache.verifier import _negation_flag, _numbers
from app.embeddings import tokenize
from scripts.stress_semantic_http import POLICY, ROOT, digest, write_csv

SOURCE = ROOT / "evaluation/runs/nq_song_stress_20261030_v3/answer_aware_sufficient/requests.csv"
EXPECTED_FAILURES = 54
MIN_AMBIGUOUS_TITLE_TOKENS = 3


def audit(output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    policy = AnswerPolicy.load(POLICY)
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        failures = [
            row for row in csv.DictReader(stream) if row["outcome"] == "incorrect_acceptance"
        ]
    if len(failures) != EXPECTED_FAILURES:
        raise ValueError(f"Expected 54 frozen suspected accepts, found {len(failures)}")
    rows = []
    for row in failures:
        incoming, stored = row["question"], row["selected_cached_query"]
        left, right = named_work(incoming), named_work(stored)
        if not left or not right:
            raise ValueError(f"Unclassified explicit subject in {row['id']}")
        titles = (left[1], right[1])
        shorter, longer = sorted(titles, key=len)
        possible_title_ambiguity = len(shorter) >= MIN_AMBIGUOUS_TITLE_TOKENS and tuple(
            longer[: len(shorter)]
        ) == tuple(shorter)
        structural_passed = (
            _numbers(incoming) == _numbers(stored)
            and _negation_flag(incoming) == _negation_flag(stored)
            and _scope_terms(tokenize(incoming)) == _scope_terms(tokenize(stored))
        )
        nli_score = float(row["nli_score"])
        rows.append(
            {
                "id": row["id"],
                "incoming_question": incoming,
                "cached_question": stored,
                "cached_answer": row["actual_answer"],
                "nq_reference": row["reference_answer"],
                "incoming_subject": " ".join(left[1]),
                "cached_subject": " ".join(right[1]),
                "different_explicit_subject": left != right,
                "retrieval_confusion": left != right,
                "structural_checks_passed": structural_passed,
                "nli_accepted_conflict": row["reason"] == "answer_accept:answer_entailment"
                and nli_score >= policy.accept_at,
                "possible_title_ambiguity": possible_title_ambiguity,
                "incomplete_reference": "unresolved_no_independent_review",
                "incorrect_label": "unresolved_no_independent_review",
                "factual_wrongness": "suspected_not_adjudicated",
                "similarity": row["similarity"],
                "nli_score": row["nli_score"],
                "source_line": row["source_line"],
                "source_url": row["source_url"],
            }
        )
    output.mkdir(parents=True)
    write_csv(output / "all_54_failure_audit.csv", rows)
    counts = {
        key: sum(str(row[key]) == "True" for row in rows)
        for key in (
            "different_explicit_subject",
            "retrieval_confusion",
            "structural_checks_passed",
            "nli_accepted_conflict",
            "possible_title_ambiguity",
        )
    }
    (output / "summary.json").write_text(
        json.dumps(
            {
                "source_sha256": digest(SOURCE),
                "policy_sha256": digest(POLICY),
                "audit_sha256": digest(output / "all_54_failure_audit.csv"),
                "rows": len(rows),
                "overlapping_cause_counts": counts,
                "unresolved_factual_labels": len(rows),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "AUDIT.md").write_text(
        "# Frozen stress-run failure audit\n\n"
        "All 54 suspected wrong accepts in the sufficient-capacity answer-aware run "
        "are listed in `all_54_failure_audit.csv`. Cause groups overlap.\n\n"
        f"- Different explicit named work and nearest-neighbour retrieval confusion: "
        f"{counts['different_explicit_subject']}/54.\n"
        f"- Earlier number, negation and scope checks passed: "
        f"{counts['structural_checks_passed']}/54.\n"
        f"- NLI accepted the conflicting answer assertion: "
        f"{counts['nli_accepted_conflict']}/54.\n"
        f"- Possible title-prefix ambiguity needing source review: "
        f"{counts['possible_title_ambiguity']}/54.\n"
        "- Incomplete NQ references or incorrect labels: unresolved for all 54 "
        "without independent answer adjudication. No count is claimed for either.\n\n"
        "Retrieval returns the nearest MiniLM question even when its named work "
        "differs. The old structural checks cover numbers, negation and scope, "
        "but not work identity. NLI then scores the two generic answer assertions "
        "as entailing and authorizes the cached answer. A high NLI score here is "
        "evidence of verifier failure on subject conflict, not evidence that the "
        "NQ reference is complete. The new guard blocks an explicit work conflict "
        "before NLI while leaving unknown forms to the existing policy.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    audit(parser.parse_args().output.resolve())
