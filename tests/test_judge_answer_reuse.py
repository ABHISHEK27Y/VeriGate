"""Judge validation and queue eligibility do not load a model in CI."""

from __future__ import annotations

import csv

from scripts.judge_answer_reuse import _parse_answer, _queue_triples, _scores

HALF = 0.5


def test_judge_score_definitions_and_abstention():
    perfect = _scores([True, False, True, False], [True, False, True, False])
    assert perfect["accuracy"] == 1.0
    assert perfect["precision"] == 1.0
    assert perfect["recall"] == 1.0
    assert perfect["cohen_kappa"] == 1.0
    conservative = _scores([True, False], [None, False])
    assert conservative["accuracy"] == HALF
    assert conservative["precision"] is None
    assert conservative["recall"] == 0.0
    assert conservative["abstain_rate"] == HALF


def test_judge_parses_only_explicit_yes_no():
    assert _parse_answer("YES.") is True
    assert _parse_answer("No, do not reuse") is False
    assert _parse_answer("Maybe") is None
    assert _parse_answer("") is None


def test_blank_review_queue_rows_are_not_model_judged(tmp_path):
    path = tmp_path / "review.tsv"
    fields = (
        "source",
        "source_id",
        "stored_query",
        "cached_answer",
        "incoming_query",
        "answer_reusable",
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t")
        writer.writeheader()
        writer.writerow(
            {
                "source": "qqp",
                "source_id": "1",
                "stored_query": "a?",
                "cached_answer": "",
                "incoming_query": "b?",
                "answer_reusable": "",
            }
        )
        writer.writerow(
            {
                "source": "paws",
                "source_id": "2",
                "stored_query": "c?",
                "cached_answer": "answer",
                "incoming_query": "d?",
                "answer_reusable": "",
            }
        )
    eligible, skipped = _queue_triples(path)
    assert skipped == 1
    assert len(eligible) == 1
    assert eligible[0].source == "paws"
