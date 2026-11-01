"""Offline checks for provenance, leakage and denominator handling."""

from pathlib import Path

import pytest

from evaluation import benchmark
from evaluation.datasets import Pair, group_split, qqp, smoke, stsb
from evaluation.protocol import Decision, bootstrap_ci, metrics, risk_coverage


def test_transitive_query_and_family_links_stay_in_one_split() -> None:
    rows = [
        Pair("A", "B", True, "fixture", "1"),
        Pair("b", "C", True, "fixture", "2"),
        Pair("D", "E", False, "fixture", "3", family="same"),
        Pair("F", "G", False, "fixture", "4", family="same"),
        Pair("H", "I", True, "fixture", "5"),
    ]
    result = group_split(rows, seed=42)
    ownership = {row.source_id: split for split, group in result.items() for row in group}
    assert ownership["1"] == ownership["2"]
    assert ownership["3"] == ownership["4"]
    assert group_split(rows, seed=42) == result
    assert sum(map(len, result.values())) == len(rows)


def test_loader_keeps_pair_label_separate_from_answer_reuse(tmp_path: Path) -> None:
    source = tmp_path / "qqp.tsv"
    source.write_text(
        "id\tquestion1\tquestion2\tis_duplicate\n1\tHow?\tWhy?\t0\n2\tA\tB\t1\n",
        encoding="utf-8",
    )
    rows = qqp(source)
    assert [row.equivalent for row in rows] == [False, True]
    assert all(row.answer_reusable is None and row.cached_answer is None for row in rows)
    with pytest.raises(ValueError, match="requires the actual cached answer"):
        Pair("A", "B", True, "fixture", "1", answer_reusable=True)


def test_stsb_threshold_is_explicit_proxy(tmp_path: Path) -> None:
    source = tmp_path / "stsb.tsv"
    source.write_text(
        "id\tsentence1\tsentence2\tscore\n1\tA\tB\t3.9\n2\tC\tD\t4.0\n",
        encoding="utf-8",
    )
    assert [row.equivalent for row in stsb(source)] == [False, True]
    with pytest.raises(ValueError, match="0..5"):
        stsb(source, threshold=6.0)


def test_metrics_do_not_invent_precision_for_reject_all() -> None:
    rows = [Decision(True, 0.7, False, "a"), Decision(False, 0.2, False, "b")]
    result = metrics(rows)
    assert result["precision"] is None
    assert result["false_hit_among_served"] is None
    assert result["coverage"] == 0
    assert risk_coverage(rows)[0]["risk"] is None
    assert bootstrap_ci(rows, "precision", resamples=10) == (None, None)


def test_metrics_have_correct_denominators() -> None:
    half = 1 / 2
    rows = [
        Decision(True, 0.9, True, "a"),
        Decision(True, 0.1, False, "b"),
        Decision(False, 0.8, True, "c"),
        Decision(False, 0.2, False, "d"),
    ]
    result = metrics(rows)
    assert result["coverage"] == half
    assert result["false_hit_among_served"] == half
    assert result["false_accept_among_negative"] == half
    assert result["recall"] == half
    assert result["auroc"] == half


def test_smoke_fixture_is_pair_only() -> None:
    rows = smoke()
    assert len(rows) == len(benchmark.POSITIVES) + len(benchmark.NEGATIVES)
    assert all(row.cached_answer is None for row in rows)
