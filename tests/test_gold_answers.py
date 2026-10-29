"""Gold-answer matching is an explicit factoid proxy, never reviewer truth."""

from __future__ import annotations

import csv
import json

import pytest

from evaluation.datasets import group_split
from evaluation.gold_answers import load_pairs, normalize_answer, reuse_ok
from evaluation.gold_model import _antonym_mismatch
from scripts.build_answer_pairs import _choose_disjoint


def test_alias_normalization_and_mismatch():
    assert normalize_answer("The U.S.A.") == "usa"
    assert reuse_ok(["The United States", "USA"], ["usa"])
    assert not reuse_ok(["12"], ["13"])
    assert not reuse_ok([], ["Paris"])
    assert _antonym_mismatch("before 2020", "after 2020") == 1.0
    assert _antonym_mismatch("Paris in France", "France includes Paris") == 0.0


def test_loader_checks_labels_and_group_split(tmp_path):
    path = tmp_path / "gold.tsv"
    fields = (
        "source_id",
        "stored_query",
        "incoming_query",
        "cached_answer",
        "stored_aliases",
        "incoming_aliases",
        "reuse_ok",
        "label_type",
    )
    rows = [
        {
            "source_id": str(index),
            "stored_query": f"Who wrote book {index}?",
            "incoming_query": f"Who authored book {index}?",
            "cached_answer": f"Author {index}",
            "stored_aliases": json.dumps([f"Author {index}"]),
            "incoming_aliases": json.dumps([f"Author {index}" if index % 2 else "Other"]),
            "reuse_ok": str(index % 2),
            "label_type": "gold_answer_match",
        }
        for index in range(8)
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    pairs, aliases = load_pairs(path)
    assert len(pairs) == len(rows)
    assert all(pair.annotation_status == "gold_answer_match" for pair in pairs)
    assert len(aliases) == len(rows) * 2
    splits = group_split(pairs, 11)
    sets = [
        {q for pair in part for q in (pair.stored_query, pair.incoming_query)}
        for part in splits.values()
    ]
    assert all(not left & right for i, left in enumerate(sets) for right in sets[i + 1 :])
    rows[0]["reuse_ok"] = "1"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="disagrees"):
        load_pairs(path)


def test_disjoint_miner_does_not_reuse_questions():
    selected = _choose_disjoint(
        [(0.9, 0, 1, False), (0.8, 0, 2, False)],
        [(0.7, 3, 4, True)],
        4,
    )
    assert len(selected) == len({True, False})
    used = [index for _, first, second, _, _ in selected for index in (first, second)]
    assert len(used) == len(set(used))
