"""Bound first-token and idle waits without switching after visible output."""

import asyncio

import fakeredis.aioredis
import httpx
import pytest

from app.config import settings
from app.providers.mock import MockProvider
from app.providers.registry import ProviderRegistry


class SlowFirst(MockProvider):
    name = "slow-first"

    async def stream(self, prompt):
        await asyncio.sleep(0.2)
        yield "too late"


class SlowIdle(MockProvider):
    name = "slow-idle"

    async def stream(self, prompt):
        yield "first"
        await asyncio.sleep(0.2)
        yield "too late"


class Unauthorized(MockProvider):
    name = "unauthorized"

    async def stream(self, prompt):
        request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
        raise httpx.HTTPStatusError("unauthorized", request=request, response=httpx.Response(401))
        yield "unreachable"  # pragma: no cover


@pytest.mark.asyncio
async def test_first_token_deadline_preserves_time_for_fallback(monkeypatch):
    monkeypatch.setattr(settings, "provider_first_token_timeout", 0.02)
    monkeypatch.setattr(settings, "provider_timeout", 1.0)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        reg = ProviderRegistry(
            providers=(SlowFirst(), MockProvider(delay=0, name_override="backup")), redis=r
        )
        name, stream = await reg.route_stream("test")
        assert name == "backup"
        assert "".join([chunk async for chunk in stream])
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_idle_deadline_fails_partial_stream_without_fallback(monkeypatch):
    monkeypatch.setattr(settings, "provider_stream_idle_timeout", 0.02)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        reg = ProviderRegistry(
            providers=(SlowIdle(), MockProvider(delay=0, name_override="backup")), redis=r
        )
        name, stream = await reg.route_stream("test")
        assert name == "slow-idle"
        with pytest.raises(TimeoutError):
            _ = [chunk async for chunk in stream]
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_unauthorized_provider_is_not_retried_on_another_model():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        reg = ProviderRegistry(providers=(Unauthorized(), MockProvider(delay=0)), redis=r)
        with pytest.raises(RuntimeError, match="rejected request"):
            await reg.route_stream("test")
    finally:
        await r.aclose()
