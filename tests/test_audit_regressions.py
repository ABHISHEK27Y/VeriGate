"""Reproductions for production failures missed by the original smoke suite."""

# ruff: noqa: PLR2004 - explicit expected counts and HTTP codes in regression tests

import asyncio
import json
from collections import Counter

import fakeredis.aioredis
import httpx
import pytest
from fastapi.testclient import TestClient

from app import budget
from app.cache.namespace import namespace
from app.cache.semantic_cache import SemanticCache
from app.cache.threshold import T_MAX, T_MIN, adaptive_threshold
from app.cache.verifier import NliVerifier, verify_equivalent
from app.cache.volatility import is_volatile
from app.config import settings
from app.providers import breaker
from app.providers.mock import MockProvider
from app.providers.openai_compat import OpenAICompatibleProvider
from app.providers.registry import ProviderRegistry
from app.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_ttl_and_other_worker_clear_are_authoritative(monkeypatch):
    monkeypatch.setattr(settings, "vector_backend", "inproc")
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    a, b = SemanticCache(r), SemanticCache(r)
    try:
        await b.lookup("reset account password", "tenant")
        await a.store("reset account password", "fresh", "tenant")
        assert (await b.lookup("reset account password", "tenant")).status == "HIT"
        await a.clear("tenant")
        assert (await b.lookup("reset account password", "tenant")).status == "MISS"
        monkeypatch.setattr(settings, "cache_ttl_sec", 1)
        await a.store("reset account password", "expiring", "tenant")
        assert (await b.lookup("reset account password", "tenant")).status == "HIT"
        await asyncio.sleep(1.1)
        assert (await b.lookup("reset account password", "tenant")).status == "MISS"
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_concurrent_writes_remain_bounded(monkeypatch):
    monkeypatch.setattr(settings, "vector_backend", "inproc")
    monkeypatch.setattr(settings, "max_cache_entries_per_tenant", 3)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    caches = [SemanticCache(r) for _ in range(5)]
    try:
        await asyncio.gather(
            *(
                caches[i % len(caches)].store(f"query {i}", f"answer {i}", "tenant")
                for i in range(50)
            )
        )
        assert await r.scard(f"{namespace()}:ids:tenant") == 3
        assert await r.zcard(f"{namespace()}:lru:tenant") == 3
        assert len([key async for key in r.scan_iter(match=f"{namespace()}:entry:tenant:*")]) == 3
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_lru_hit_changes_eviction_order(monkeypatch):
    monkeypatch.setattr(settings, "vector_backend", "inproc")
    monkeypatch.setattr(settings, "max_cache_entries_per_tenant", 2)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache = SemanticCache(r)
    try:
        await cache.store("plan 1", "one", "t")
        await cache.store("plan 2", "two", "t")
        assert (await cache.lookup("plan 1", "t")).status == "HIT"
        await cache.store("plan 3", "three", "t")
        assert (await cache.lookup("plan 1", "t")).status == "HIT"
        assert (await cache.lookup("plan 2", "t")).status == "MISS"
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_budget_and_rate_limit_concurrency_hides_credentials(monkeypatch):
    monkeypatch.setattr(settings, "daily_request_budget", 5)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = RateLimiter(r)
    limiter.capacity, limiter.refill = 5, 0.001
    try:
        allowed = await asyncio.gather(
            *(budget.check_and_count("secret-token", r) for _ in range(50))
        )
        assert sum(allowed) == 5
        assert await budget.used_today("secret-token", r) == 5
        results = await asyncio.gather(*(limiter.allow("secret-token") for _ in range(50)))
        assert sum(result[0] for result in results) == 5
        assert all(["secret-token" not in key async for key in r.scan_iter()])
    finally:
        await r.aclose()


@pytest.mark.parametrize(
    "pair",
    [
        ("it isn't working", "it is working"),
        ("it doesn’t work", "it does work"),
        ("Austria capital", "Australia capital"),
    ],
)
def test_verifier_edge_cases(pair):
    assert not verify_equivalent(*pair)[0]


def test_conversation_context_is_not_silently_discarded(client):
    response = client.post(
        "/v1/chat",
        headers={"x-api-key": "demo-key-123"},
        json={
            "messages": [
                {"role": "system", "content": "French only"},
                {"role": "user", "content": "Hello"},
            ],
        },
    )
    assert response.status_code == 422


def test_metrics_token_and_api_key_are_distinct(client):
    assert client.get("/metrics", headers={"x-api-key": "demo-key-123"}).status_code == 401
    response = client.get("/health")
    assert len(response.headers["x-request-id"]) == 32


@pytest.mark.asyncio
async def test_all_open_breakers_do_not_call_upstream():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider = MockProvider(delay=0)
    reg = ProviderRegistry(providers=(provider,), redis=r)
    try:
        for _ in range(settings.breaker_fail_threshold):
            await breaker.record_failure(provider.name, r)
        with pytest.raises(RuntimeError, match="unavailable"):
            await reg.route_stream("hello")
        await r.set(breaker._keys("mock")[0], "0", ex=60)
        results = await asyncio.gather(*(breaker.is_open("mock", r) for _ in range(30)))
        assert results.count(False) == 1
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_provider_midstream_failure_is_recorded():
    class BrokenStream(MockProvider):
        async def stream(self, prompt):
            yield "first"
            raise RuntimeError("interrupted")

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    reg = ProviderRegistry(providers=(BrokenStream(),), redis=r)
    try:
        _, stream = await reg.route_stream("test")
        with pytest.raises(RuntimeError, match="interrupted"):
            _ = [chunk async for chunk in stream]
        assert int(await r.get(breaker._keys("mock")[1])) == 1
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_openai_compatible_http_path(monkeypatch):
    real_client = httpx.AsyncClient

    async def upstream(request):
        assert request.headers["authorization"] == "Bearer test-upstream"
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n'
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(upstream), **kwargs),
    )
    provider = OpenAICompatibleProvider(
        "test", "test-upstream", "https://example.invalid/v1", "model"
    )
    assert "".join([chunk async for chunk in provider.stream("hello")]) == "Hello"


def test_stream_preserves_multiline_text(client):
    class Multiline(MockProvider):
        async def stream(self, prompt):
            yield "first\n\ndata: injected\nlast"

    client.app.state.provider_registry = ProviderRegistry(
        providers=(Multiline(),), redis=client.app.state.redis
    )
    for _ in range(2):
        result = client.post(
            "/v1/chat/stream",
            headers={"x-api-key": "demo-key-123"},
            json={"prompt": "line example"},
        )
        lines = [line[6:] for line in result.text.splitlines() if line.startswith("data: ")]
        assert lines[-1] == "[DONE]"
        assert "".join(json.loads(value) for value in lines[:-1]) == "first\n\ndata: injected\nlast"


def test_separate_lifespans_do_not_share_redis():
    # Even overlapping clients must not close each other's app-owned Redis connection.
    from fastapi import FastAPI  # noqa: PLC0415 - local test setup

    from app.main import lifespan  # noqa: PLC0415 - local test setup

    one, two = FastAPI(lifespan=lifespan), FastAPI(lifespan=lifespan)
    with TestClient(one), TestClient(two):
        assert one.state.redis is not two.state.redis
        assert one.state.model is not two.state.model


def test_fifty_concurrent_http_requests(client):
    async def burst():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://test"
        ) as c:
            responses = await asyncio.gather(
                *(
                    c.post(
                        "/v1/chat",
                        json={"prompt": f"burst {i}"},
                        headers={"x-api-key": "demo-key-123"},
                    )
                    for i in range(50)
                )
            )
        codes = Counter(response.status_code for response in responses)
        assert set(codes) <= {200, 429}
        assert codes[200] <= 5
        assert codes[429] > 0

    client.portal.call(burst)


def test_nli_unavailable_fails_closed():
    verifier = NliVerifier()
    verifier.unavailable = True
    assert verify_equivalent("reset password", "reset password", True, verifier) == (
        False,
        "nli_unavailable",
    )


def test_clock_queries_bypass_but_time_complexity_is_stable():
    assert is_volatile("what time is it in Delhi")
    assert is_volatile("show prices for this product")
    assert not is_volatile("explain time complexity of binary search")


def test_adaptive_threshold_varies_and_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "cache_similarity_base", 0.72)
    assert adaptive_threshold("plan 50", 1) > adaptive_threshold("explain account configuration")
    for value in (-10, 10):
        monkeypatch.setattr(settings, "cache_similarity_base", value)
        assert T_MIN <= adaptive_threshold("Austria plan 50", 1) <= T_MAX


def test_production_rejects_default_configuration(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "redis_url", "")
    with pytest.raises(ValueError, match="shared Redis"):
        settings.validate_production()


def test_upstream_outage_returns_502(client):
    class Broken(MockProvider):
        async def stream(self, prompt):
            raise RuntimeError("private upstream diagnostic")
            yield ""  # pragma: no cover

    client.app.state.provider_registry = ProviderRegistry(
        providers=(Broken(),), redis=client.app.state.redis
    )
    for endpoint in ("/v1/chat", "/v1/chat/stream"):
        response = client.post(
            endpoint, json={"prompt": "outage"}, headers={"x-api-key": "demo-key-123"}
        )
        assert response.status_code == 502
        assert "private" not in response.text
