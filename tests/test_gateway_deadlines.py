"""Lookup queueing and provider generation use distinct bounded deadlines."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

import app.main as gateway_main
from app.cache.semantic_cache import LookupResult, SemanticCache
from app.providers.mock import MockProvider

HEADERS = {"x-api-key": "demo-key-123"}


@pytest.mark.asyncio
async def test_slow_lookup_does_not_lock_an_exact_request_in_same_scope(monkeypatch) -> None:
    cache = SemanticCache(fakeredis.aioredis.FakeRedis(decode_responses=True))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def controlled_lookup(query: str, _tenant: str) -> LookupResult:
        if query == "slow paraphrase":
            entered.set()
            await release.wait()
        return LookupResult(status="HIT", answer="answer", reason="exact_match")

    monkeypatch.setattr(cache, "_lookup", controlled_lookup)
    slow = asyncio.create_task(cache.lookup("slow paraphrase", "same-tenant"))
    try:
        await entered.wait()
        fast = await asyncio.wait_for(cache.lookup("exact repeat", "same-tenant"), timeout=0.05)
        assert fast.status == "HIT"
    finally:
        release.set()
        await slow
        await cache.redis.aclose()


def test_cache_lookup_budget_falls_back_with_reason(client, monkeypatch) -> None:
    client.app.state.config = client.app.state.config.model_copy(
        update={"cache_lookup_timeout_sec": 0.02, "request_deadline_sec": 1.0}
    )

    async def delayed_lookup(*_args):
        await asyncio.sleep(0.1)
        return LookupResult(status="MISS", reason="late_lookup"), "private"

    monkeypatch.setattr(gateway_main, "_lookup_with_overlay", delayed_lookup)
    response = client.post("/v1/chat", headers=HEADERS, json={"prompt": "Explain retry backoff"})
    assert response.status_code == 200  # noqa: PLR2004
    assert response.json()["cache"] == "MISS"
    assert response.json()["note"] == "cache_lookup_timeout"
    assert response.json()["provider_invoked"] is True


def test_expired_request_deadline_never_dispatches_provider(client, monkeypatch) -> None:
    client.app.state.config = client.app.state.config.model_copy(
        update={"cache_lookup_timeout_sec": 0.1, "request_deadline_sec": 0.03}
    )
    calls = []
    provider = client.app.state.provider_registry.providers[0]

    async def counted_stream(_prompt):
        calls.append(1)
        yield "answer"

    provider.stream = counted_stream

    async def delayed_lookup(*_args):
        await asyncio.sleep(0.08)
        return LookupResult(status="MISS", reason="late_lookup"), "private"

    monkeypatch.setattr(gateway_main, "_lookup_with_overlay", delayed_lookup)
    response = client.post("/v1/chat", headers=HEADERS, json={"prompt": "Explain retry backoff"})
    assert response.status_code == 504  # noqa: PLR2004
    assert calls == []


def test_stream_provider_budget_starts_after_lookup(client, monkeypatch) -> None:
    client.app.state.config = client.app.state.config.model_copy(
        update={
            "cache_lookup_timeout_sec": 0.3,
            "provider_timeout": 0.1,
            "request_deadline_sec": 1.0,
        }
    )
    provider = client.app.state.provider_registry.providers[0]
    assert isinstance(provider, MockProvider)
    provider.delay = 0.005

    async def delayed_lookup(*_args):
        await asyncio.sleep(0.15)
        return LookupResult(status="MISS", reason="empty_cache"), "private"

    monkeypatch.setattr(gateway_main, "_lookup_with_overlay", delayed_lookup)
    response = client.post(
        "/v1/chat/stream", headers=HEADERS, json={"prompt": "Explain retry backoff"}
    )
    assert response.status_code == 200  # noqa: PLR2004
    assert "event: error" not in response.text
    assert "data: [DONE]" in response.text
