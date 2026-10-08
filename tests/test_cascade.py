"""Cost-aware cascade: complexity scoring + routing (easy→cheap, hard→strong)."""
import asyncio

from app.complexity import complexity_score, is_hard
from app.providers import registry
from app.providers.mock import MockProvider


def test_complexity_easy_vs_hard():
    assert not is_hard("what is the capital of France")
    assert is_hard("explain why quicksort is O(n log n) on average and prove it")
    assert complexity_score("explain and compare microservices vs monolith tradeoffs") > \
           complexity_score("what is 2 + 2")


def test_cascade_routes_by_complexity():
    registry.set_cascade(MockProvider(name_override="cheap"),
                         MockProvider(name_override="strong"))
    try:
        easy, _ = asyncio.run(registry.route_stream("who wrote Hamlet"))
        hard, _ = asyncio.run(registry.route_stream(
            "design a distributed rate limiter and analyze the tradeoffs step by step"))
        assert easy == "cheap"
        assert hard == "strong"
    finally:
        registry.set_cascade(None, None)   # reset global state
