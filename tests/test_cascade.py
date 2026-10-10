"""Cost-aware cascade: complexity scoring + routing (easy→cheap, hard→strong)."""

import asyncio

from app.complexity import complexity_score, is_hard
from app.providers import registry
from app.providers.mock import MockProvider


def test_complexity_easy_vs_hard():
    assert not is_hard("what is the capital of France")
    assert is_hard("explain why quicksort is O(n log n) on average and prove it")
    assert complexity_score(
        "explain and compare microservices vs monolith tradeoffs"
    ) > complexity_score("what is 2 + 2")


def test_cascade_routes_by_complexity():
    async def run():
        reg = registry.ProviderRegistry(
            providers=(),
            cascade={
                "cheap": MockProvider(name_override="cheap"),
                "strong": MockProvider(name_override="strong"),
            },
        )
        try:
            easy, stream = await reg.route_stream("who wrote Hamlet")
            _ = [chunk async for chunk in stream]
            hard, stream = await reg.route_stream(
                "design a distributed rate limiter and analyze the tradeoffs step by step"
            )
            _ = [chunk async for chunk in stream]
            assert easy == "cheap"
            assert hard == "strong"
        finally:
            await reg.redis.aclose()

    asyncio.run(run())
