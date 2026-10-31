"""Gold-answer matching is an explicit factoid proxy, never reviewer truth."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from evaluation.datasets import Pair, group_split
from evaluation.gold_answers import (
    cached_answer_reference_match,
    lenient_reuse_ok,
    load_pairs,
    normalize_answer,
    reuse_ok,
)
from evaluation.gold_model import _antonym_mismatch, _question_component_ids
from scripts.build_answer_pairs import (
    Question,
    _choose_pairs,
    _entity_span_swap,
    _negative_candidates,
)

MAX_USES = 2
SHARED_QUERY_ID = 2


def test_alias_normalization_and_mismatch():
    assert normalize_answer("The U.S.A.") == "usa"
    assert reuse_ok(["The United States", "USA"], ["usa"])
    assert not reuse_ok(["12"], ["13"])
    assert reuse_ok(["John Megna", "Brock Peters"], ["Brock Peters"])
    assert not cached_answer_reference_match("John Megna", ["Brock Peters"])
    assert not cached_answer_reference_match("John Smith", ["John Jones"])
    assert not cached_answer_reference_match("1 January 2000", ["31 December 2000"])


def test_lenient_label_is_separate_and_can_overmatch() -> None:
    assert not reuse_ok(["1969"], ["July 1969"])
    assert lenient_reuse_ok(["1969"], ["July 1969"])
    assert lenient_reuse_ok(["Wilt Chamberlain"], ["Chamberlain, Wilt"])
    assert lenient_reuse_ok(["John Smith"], ["James Smith"])
    assert not lenient_reuse_ok(["1969"], ["1970"])
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


def test_positive_pairs_are_disjoint():
    selected = _choose_pairs(
        [(0.9, 0, 1, "positive"), (0.8, 0, 2, "positive")],
        [(0.7, 3, 4, "number_swap")],
        4,
        minimum=2,
    )
    assert len(selected) == len({True, False})
    used = [index for _, first, second, _, _ in selected for index in (first, second)]
    assert len(used) == len(set(used))


def test_negative_question_reuse_is_capped_at_two():
    selected = _choose_pairs(
        [(0.9, 0, 1, "positive")],
        [(0.9, 2, 3, "number_swap"), (0.8, 2, 4, "entity_span_swap")],
        3,
        minimum=3,
    )
    negatives = [item for item in selected if not item[3]]
    assert len(negatives) == MAX_USES
    assert sum(SHARED_QUERY_ID in (item[1], item[2]) for item in negatives) == MAX_USES
    pairs = [
        Pair(str(left), str(right), label, "nq_open", str(index))
        for index, (_, left, right, label, _) in enumerate(selected)
    ]
    splits = group_split(pairs, 11)
    locations = {
        pair.source_id: split for split, split_pairs in splits.items() for pair in split_pairs
    }
    negative_ids = [str(index) for index, item in enumerate(selected) if not item[3]]
    assert locations[negative_ids[0]] == locations[negative_ids[1]]
    group_ids = _question_component_ids(pairs)
    assert group_ids[int(negative_ids[0])] == group_ids[int(negative_ids[1])]


def test_structural_negative_categories_without_embedding_nearest_neighbours():
    rows = [
        ("who directed the movie dune", "Denis Villeneuve"),
        ("who directed the movie titanic", "James Cameron"),
        ("who wrote the movie dune", "Jon Spaihts"),
        ("who directed dune", "Denis Villeneuve"),
        ("who wrote dune", "Frank Herbert"),
        ("who won the 2018 final", "France"),
        ("who won the 2019 final", "Brazil"),
    ]
    questions = [
        Question(i, text, (answer,), frozenset({answer})) for i, (text, answer) in enumerate(rows)
    ]
    vectors = np.ones((len(questions), 4), dtype=np.float32) / 2
    kinds = {kind for _, _, _, kind in _negative_candidates(questions, vectors)}
    assert {"entity_span_swap", "attribute_swap", "number_swap"} <= kinds
    assert _entity_span_swap(rows[0][0], rows[1][0])


def test_directional_loader_rejects_cast_list_false_positive(tmp_path) -> None:
    path = tmp_path / "directional.tsv"
    row = {
        "source_id": "cast",
        "stored_query": "who starred in to kill a mockingbird",
        "incoming_query": "who played tom in to kill a mockingbird",
        "cached_answer": "John Megna",
        "stored_aliases": json.dumps(["John Megna", "Brock Peters"]),
        "incoming_aliases": json.dumps(["Brock Peters"]),
        "reuse_ok": "1",
        "label_type": "cached_answer_reference_match",
    }
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=row, delimiter="\t")
        writer.writeheader()
        writer.writerow(row)
    with pytest.raises(ValueError, match="disagrees"):
        load_pairs(path)
