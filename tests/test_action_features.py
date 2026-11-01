"""Supported action evidence keeps inflections and target-sensitive meaning."""

from __future__ import annotations

import pytest

from app.cache.action_features import extract_actions
from app.cache.applicability import assess
from app.cache.technical_identity import compare


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Removing read permission from a user", "revoke"),
        ("Remove a Redis key", "delete"),
        ("Creating a backup of PostgreSQL", "backup"),
        ("Restoring a backup of PostgreSQL", "restore"),
        ("Previewing a deployment", "plan"),
        ("Deploying a release", "deploy"),
        ("What command restarts the worker?", "restart"),
        ("What policy gives read access?", "grant"),
    ],
)
def test_action_evidence_has_source_span(text: str, expected: str) -> None:
    result = extract_actions(text)
    assert expected in result.action_names
    assert any(text[item.start : item.end] == item.surface for item in result.evidence)


def test_unresolved_remove_target_is_unknown() -> None:
    result = extract_actions("How do I remove it?")
    assert result.unknown
    assert not result.action_names


def test_action_normalization_is_shared_between_guards() -> None:
    stored = "How do I remove read permission from Redis?"
    answer = "Remove read permission from Redis by revoking it."
    incoming = "How do I delete a Redis key?"
    assert compare(incoming, stored) == "technical_action_conflict"
    check = assess(incoming, stored, answer)
    assert check is not None
    assert (check.action, check.reason) == ("VERIFY", "applicability_permission_missing")
    stored = "How do I restore a PostgreSQL backup?"
    answer = "Restore the PostgreSQL backup."
    incoming = "How do I create a PostgreSQL backup?"
    assert compare(incoming, stored) == "technical_action_conflict"
    check = assess(incoming, stored, answer)
    assert check is not None
    assert (check.action, check.reason) == ("REJECT", "applicability_action_conflict")
