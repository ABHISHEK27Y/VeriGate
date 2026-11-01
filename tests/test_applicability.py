"""Experimental applicability must preserve paraphrases and benign omissions."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cache.answer_policy import AnswerPolicy
from app.cache.applicability import assess

ARTIFACT = Path(__file__).resolve().parents[1] / "app/cache/artifacts/answer_policy_v1.json"


class AlwaysEntails:
    calls = 0

    def entail_prob(self, _premise: str, _hypothesis: str) -> float:
        self.calls += 1
        return 0.99


@pytest.mark.parametrize(
    ("stored", "answer", "incoming", "action", "reason"),
    [
        (
            "How do I plan a Terraform change for workspace alpha?",
            "Run a Terraform plan for workspace alpha.",
            "How do I apply a Terraform change for workspace alpha?",
            "REJECT",
            "applicability_action_conflict",
        ),
        (
            "How do I plan a Terraform change for workspace alpha?",
            "Run a Terraform plan for workspace alpha.",
            "How do I change Terraform workspace alpha?",
            "REJECT",
            "applicability_action_conflict",
        ),
        (
            "How do I run a Pytest test marked slow?",
            "Run the Pytest test marked slow.",
            "How do I run a Pytest test?",
            "VERIFY",
            "applicability_marker_missing",
        ),
        (
            "How do I send an HTTP PUT request to /items?",
            "Send a PUT request to /items.",
            "How do I send a request to /items?",
            "VERIFY",
            "applicability_http_method_missing",
        ),
        (
            "How do I roll back a Kubernetes deployment in staging?",
            "Roll back the staging deployment.",
            "How do I roll back the deployment?",
            "VERIFY",
            "applicability_environment_missing",
        ),
        (
            "How do I grant contents read access?",
            "Set permissions: contents: read for read access.",
            "How do I grant contents write access?",
            "REJECT",
            "applicability_permission_conflict",
        ),
    ],
)
def test_supported_conflict_or_missing_requirement(stored, answer, incoming, action, reason):
    result = assess(incoming, stored, answer)
    assert result is not None
    assert (result.action, result.reason) == (action, reason)


@pytest.mark.parametrize(
    ("stored", "answer", "incoming"),
    [
        (
            "How do I plan a Terraform change for workspace alpha?",
            "Run a Terraform plan for workspace alpha.",
            "How can I preview a Terraform change for workspace alpha?",
        ),
        (
            "How do I roll back a Kubernetes deployment in production?",
            "Roll back the production deployment.",
            "How can I revert the Kubernetes deployment in prod?",
        ),
        (
            "How do I restart Redis in staging?",
            "Run the Redis restart command.",
            "How can I reboot Redis?",
        ),
        (
            "How do I send an HTTP PUT request to /items?",
            "Send a PUT request to /items.",
            "What is the way to send a PUT request to /items?",
        ),
        (
            "How do I use TLS version 1.3 in staging?",
            "Set the TLS protocol version to 1.3.",
            "How can I configure TLS v1.3?",
        ),
        (
            "How do I restart a service in staging?",
            "Restart the service; the same command works in any environment.",
            "How do I restart the service?",
        ),
    ],
)
def test_valid_paraphrase_or_benign_omission_is_not_blocked(stored, answer, incoming):
    assert assess(incoming, stored, answer) is None


def test_experimental_flag_checks_applicability_before_nli() -> None:
    policy = AnswerPolicy.load(ARTIFACT)
    verifier = AlwaysEntails()
    stored = "How do I plan a Terraform change for workspace alpha?"
    answer = "Run a Terraform plan for workspace alpha."
    bad = policy.decide(
        "How do I apply a Terraform change for workspace alpha?",
        stored,
        answer,
        0.95,
        verifier,
        applicability_guard=True,
    )
    assert (bad.action, bad.reason) == ("REJECT", "applicability_action_conflict")
    assert verifier.calls == 0
    good = policy.decide(
        "How can I preview a Terraform change for workspace alpha?",
        stored,
        answer,
        0.95,
        verifier,
        applicability_guard=True,
    )
    assert good.action == "ACCEPT"
    assert verifier.calls == 1
