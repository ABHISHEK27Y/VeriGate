"""Review completion must be explicit and cannot be inferred from paraphrase labels."""

import csv
from pathlib import Path

import pytest

from evaluation.datasets import reviewed_answers
from scripts.build_answer_review_queue import FIELDS


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_unreviewed_rows_are_not_labels(tmp_path: Path) -> None:
    path = tmp_path / "review.tsv"
    _write(
        path,
        [
            {
                "source": "qqp",
                "source_id": "1",
                "stored_query": "A",
                "incoming_query": "B",
                "pair_label": "1",
                "review_status": "unreviewed",
            }
        ],
    )
    assert reviewed_answers(path) == []


def test_resolved_answer_label_can_disagree_with_pair_label(tmp_path: Path) -> None:
    path = tmp_path / "review.tsv"
    row = {
        "source": "qqp",
        "source_id": "1",
        "family": "one",
        "stored_query": "A",
        "cached_answer": "Old version only",
        "incoming_query": "B",
        "pair_label": "1",
        "answer_reusable": "0",
        "reason": "outdated answer",
        "reviewer_1": "r1",
        "reviewer_2": "r2",
        "review_status": "resolved_two_reviewers",
        "tenant_id": "tenant",
        "context_version": "none",
        "answer_version": "v1",
    }
    _write(path, [row])
    [pair] = reviewed_answers(path)
    assert pair.equivalent
    assert pair.answer_reusable is False
    row["reviewer_2"] = "r1"
    _write(path, [row])
    with pytest.raises(ValueError, match="two distinct reviewers"):
        reviewed_answers(path)
