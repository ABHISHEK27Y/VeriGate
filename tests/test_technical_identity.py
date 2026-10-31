"""Technical identity mismatches are checked before NLI can authorize reuse."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cache.answer_policy import AnswerPolicy
from app.cache.technical_identity import compare, extract

ARTIFACT = Path(__file__).resolve().parents[1] / "app/cache/artifacts/answer_policy_v1.json"


class AlwaysEntails:
    calls = 0

    def entail_prob(self, _premise: str, _hypothesis: str) -> float:
        self.calls += 1
        return 0.99


@pytest.mark.parametrize(
    ("stored", "incoming", "reason"),
    [
        ("How do I restart Redis?", "How do I restart PostgreSQL?", "technical_product_conflict"),
        (
            "How do I create a Redis key?",
            "How do I delete a Redis key?",
            "technical_action_conflict",
        ),
        (
            "How do I deploy Docker in staging?",
            "How do I deploy Docker in production?",
            "technical_environment_conflict",
        ),
        (
            "What does `CACHE_MATCH_MODE=exact` do in Python?",
            "What does `CACHE_MATCH_MODE=semantic` do in Python?",
            "technical_identifier_conflict",
        ),
    ],
)
def test_conflicts_block_high_nli(stored: str, incoming: str, reason: str) -> None:
    verifier = AlwaysEntails()
    decision = AnswerPolicy.load(ARTIFACT).decide(
        incoming, stored, "An answer", 0.95, verifier, technical_guard=True
    )
    assert decision.action == "REJECT"
    assert decision.reason == reason
    assert verifier.calls == 0


@pytest.mark.parametrize(
    ("stored", "incoming"),
    [
        ("How do I restart PostgreSQL in production?", "How can I reboot Postgres in prod?"),
        ("How do I restart Kubernetes?", "How can I reboot K8s?"),
        ("How do I remove a Redis key?", "How do I delete a Redis key?"),
        ("How do I backup MySQL?", "What is the way to make a MySQL backup?"),
    ],
)
def test_supported_aliases_reach_answer_nli(stored: str, incoming: str) -> None:
    verifier = AlwaysEntails()
    decision = AnswerPolicy.load(ARTIFACT).decide(
        incoming, stored, "Use the CLI", 0.95, verifier, technical_guard=True
    )
    assert decision.action == "ACCEPT"
    assert verifier.calls == 1


def test_extraction_uncertainty_abstains_and_unrelated_questions_pass() -> None:
    assert (
        compare("How do I restart Redis?", "How do I restart it?") == "technical_identity_uncertain"
    )
    assert compare("Who founded Eastmere?", "Who established Eastmere?") is None
    assert extract("How do I update `CACHE_MATCH_MODE=exact` in Redis?").identifiers == frozenset(
        {"cache_match_mode=exact"}
    )
