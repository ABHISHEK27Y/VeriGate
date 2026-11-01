"""The descriptive pilot must keep its input freeze and exclusion boundary."""

import hashlib
import json

import pytest

from scripts import run_realistic_query_pilot as pilot


def test_selection_excludes_prior_questions_and_deduplicates(tmp_path, monkeypatch) -> None:
    source = tmp_path / "dev.jsonl"
    items = [
        {"question": "Earlier question", "answer": ["A"]},
        {"question": "New question one", "answer": ["B"]},
        {"question": "  new   question ONE  ", "answer": ["B"]},
        {"question": "New question two", "answer": ["C"]},
    ]
    source.write_text("\n".join(json.dumps(item) for item in items) + "\n", encoding="utf-8")
    monkeypatch.setattr(pilot, "SOURCE", source)
    monkeypatch.setattr(pilot, "_exclusions", lambda: {"earlier question"})
    freeze = {"selection": {"stored_count": 1, "distinct_incoming_count": 1}}
    stored, incoming, eligible = pilot._select(freeze)
    expected = {
        "new question one",
        "new question two",
    }
    assert eligible == len(expected)
    assert {pilot._norm(row["query"]) for row in [*stored, *incoming]} == expected


def test_changed_source_is_rejected_before_pilot(tmp_path, monkeypatch) -> None:
    source = tmp_path / "dev.jsonl"
    source.write_text('{"question":"changed","answer":["A"]}\n', encoding="utf-8")
    monkeypatch.setattr(pilot, "SOURCE", source)
    freeze = {
        "source_sha256": hashlib.sha256(b"original").hexdigest(),
        "policy": {},
    }
    with pytest.raises(ValueError, match="input differs"):
        pilot._validate_freeze(freeze)
