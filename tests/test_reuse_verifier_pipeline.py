"""Alternative verifier stays opt-in and fails closed on unvalidated evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cache.answer_policy import AnswerPolicy
from app.cache.reuse_verifier import (
    FORMAT_VERSION,
    ReuseAssessment,
    TaskReuseVerifier,
    format_input,
    sha256_file,
)
from app.config import get_settings
from scripts.train_reuse_verifier import choose_threshold, load_rows, split_rows


def _artifact(tmp_path: Path, *, validated: bool = True) -> Path:
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "format_version": FORMAT_VERSION,
                "base_model": "cross-encoder/nli-deberta-v3-xsmall",
                "base_revision": get_settings().nli_revision,
                "input_format": "stored-question-and-answer paired with incoming-question",
                "accept_at": 0.9,
                "calibration": {"validated": validated},
                "files": {"config.json": sha256_file(tmp_path / "config.json")},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_three_field_format_and_artifact_integrity(tmp_path: Path) -> None:
    first, second = format_input("stored?", "cached answer", "incoming?")
    assert "stored?" in first and "cached answer" in first and "incoming?" in second
    path = _artifact(tmp_path)
    verifier = TaskReuseVerifier(path)
    assert len(verifier.identity) == len("0" * 64)
    (tmp_path / "config.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="file changed"):
        TaskReuseVerifier(path)


def test_unvalidated_artifact_cannot_load(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="calibration"):
        TaskReuseVerifier(_artifact(tmp_path, validated=False))


def test_task_score_only_accepts_above_artifact_threshold(tmp_path: Path, monkeypatch) -> None:
    verifier = TaskReuseVerifier(_artifact(tmp_path))
    policy = AnswerPolicy("model", "revision", 0.99, 0.1, 0.35, "v", ())
    monkeypatch.setattr(verifier, "assess_reuse", lambda *_: ReuseAssessment(0.95, "ok", 20))
    assert policy.decide("new?", "old?", "answer", 0.9, verifier).action == "ACCEPT"
    monkeypatch.setattr(verifier, "assess_reuse", lambda *_: ReuseAssessment(0.89, "ok", 20))
    assert policy.decide("new?", "old?", "answer", 0.9, verifier).action == "VERIFY"
    monkeypatch.setattr(
        verifier, "assess_reuse", lambda *_: ReuseAssessment(None, "unavailable", None)
    )
    assert policy.decide("new?", "old?", "answer", 0.9, verifier).action == "VERIFY"


def test_calibration_requires_nonzero_coverage_and_zero_observed_errors() -> None:
    with pytest.raises(ValueError, match="reject-all"):
        choose_threshold([(0.9, 1)] * 20 + [(0.8, 0)] * 20)
    threshold, evidence = choose_threshold([(0.9, 1)] * 60 + [(0.8, 0)] * 60)
    assert threshold == max(score for score, _ in [(0.9, 1), (0.8, 0)])
    assert evidence["accepted"] == len([(0.9, 1)] * 60)
    assert evidence["wrong_accepts"] == 0


def test_existing_authored_data_is_too_small_for_training() -> None:
    path = Path("evaluation/runs/reuse_verifier_development_20261101_v1/pairs.csv")
    if path.exists():
        with pytest.raises(ValueError, match="independently labelled rows"):
            load_rows(path)


def test_grouped_split_rejects_cross_source_family() -> None:
    rows = [
        {
            "source": source,
            "family": "same-family",
            "stored_question": "a?",
            "stored_answer": "a",
            "incoming_question": "b?",
            "reuse_ok": "1",
            "label_provenance": "expert_reviewed",
        }
        for source in ("one", "two", "three")
    ]
    with pytest.raises(ValueError, match="family crosses"):
        split_rows(rows)
