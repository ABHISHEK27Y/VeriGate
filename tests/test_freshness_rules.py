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
