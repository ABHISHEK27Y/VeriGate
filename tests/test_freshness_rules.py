"""Definitional terms can be stable; uncertain live values still bypass."""

import pytest

from app.cache.volatility import is_volatile


@pytest.mark.parametrize(
    "query",
    [
        "What is a credit score?",
        "What does current account mean in banking?",
        "Define price elasticity of demand.",
        "What is the difference between stock and flow variables?",
        "How is a credit score calculated in principle?",
    ],
)
def test_clear_concept_requests_are_cacheable(query: str) -> None:
    assert not is_volatile(query)


@pytest.mark.parametrize(
    "query",
    [
        "What is a credit score right now?",
        "Define the latest stock price today.",
        "What does the current account balance mean today?",
        "What is the price of gold?",
        "Show the cricket score",
        "What is the current weather?",
    ],
)
def test_explicit_time_and_uncertain_values_still_bypass(query: str) -> None:
    assert is_volatile(query)


@pytest.mark.parametrize(
    "query",
    [
        # Technical procedures whose answer is stable even though a value or
        # recency word appears. Earlier these were all wrongly bypassed.
        "How do I get the current user in a Django request?",
        "How do I read the current branch name in a shell script?",
        "How do I get the latest commit hash in git?",
        "How do I live-reload nginx after a config change?",
        "How do I fetch the most recent rows from a Kafka topic?",
        "How do I add a price field to a Postgres table?",
        "How do I set the CPU temperature threshold in a systemd unit?",
        "How do I compute an F1 score in PyTorch?",
        "How do I keep a dependency up to date with Renovate?",
        "How do I list stock levels from the inventory API?",
        # A value noun used as a compound modifier names a concept, not a value.
        "What is the price mechanism in economics?",
    ],
)
def test_technical_procedures_and_concepts_are_cacheable(query: str) -> None:
    assert not is_volatile(query)


@pytest.mark.parametrize(
    "query",
    [
        # Value requests remain volatile even without an explicit today/now.
        "What is the latest release version of Python?",
        "Who is the current CEO of the company?",
        "What are the live cricket scores?",
        "What is the price of Bitcoin?",
        "What are the most recent headlines in the news?",
    ],
)
def test_value_requests_bypass_without_explicit_time_word(query: str) -> None:
    assert is_volatile(query)


def test_procedure_with_absolute_time_still_bypasses() -> None:
    # A "how do I" procedure is rescued over value words, but not over today/now.
    assert is_volatile("How do I check the stock price today?")
    assert not is_volatile("How do I check the stock price field?")
