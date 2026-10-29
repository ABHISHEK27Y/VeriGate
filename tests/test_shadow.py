"""Opt-in shadow work must stay off the response path and remain unlabelled."""

from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest
from conftest import HEADERS

from app.cache.namespace import namespace
from app.config import Settings, _runtime, snapshot
from app.identity import tenant_id
from app.shadow import ShadowAuditor

TTL_SECONDS = 60
TWO_TENANTS = 2


class FakeProvider:
    def __init__(self, answer: str = "fresh") -> None:
        self.answer = answer
        self.calls = 0
        self.release = asyncio.Event()

    async def route_stream(self, prompt: str):
        self.calls += 1

        async def stream():
            await self.release.wait()
            yield self.answer

        return "fake", stream()


@pytest.mark.asyncio
async def test_shadow_is_off_by_default():
    provider = FakeProvider()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    auditor = ShadowAuditor(redis, provider)
    assert not auditor.maybe_schedule("question", "cached", "tenant-a")
    assert provider.calls == 0
    await auditor.aclose()
    await redis.aclose()


@pytest.mark.asyncio
async def test_shadow_is_nonblocking_tenant_scoped_and_unreviewed():
    token = _runtime.set(
        snapshot(
            Settings(
                shadow_enabled=True,
                shadow_sample_rate=1,
                shadow_max_pending=1,
                shadow_review_limit=1,
                cache_ttl_sec=TTL_SECONDS,
            )
        )
    )
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider = FakeProvider()
    auditor = ShadowAuditor(redis, provider)
    try:
        assert auditor.maybe_schedule("question-a", "cached-a", "tenant-a")
        assert not auditor.maybe_schedule("question-b", "cached-b", "tenant-b")
        await asyncio.sleep(0)
        assert provider.calls == 1
        key_a = f"{namespace()}:shadow:review:tenant-a"
        assert await redis.llen(key_a) == 0  # upstream still pending
        provider.release.set()
        await asyncio.gather(*auditor._tasks)
        rows = await redis.lrange(key_a, 0, -1)
        assert len(rows) == 1
        record = json.loads(rows[0])
        assert record["cached_answer"] == "cached-a"
        assert record["fresh_answer"] == "fresh"
        assert record["review_status"] == "unreviewed"
        assert record["label"] is None
        assert await redis.llen(f"{namespace()}:shadow:review:tenant-b") == 0
        assert 0 < await redis.ttl(key_a) <= TTL_SECONDS
    finally:
        await auditor.aclose()
        await redis.aclose()
        _runtime.reset(token)


@pytest.mark.asyncio
async def test_shadow_shutdown_cancels_pending_provider():
    token = _runtime.set(snapshot(Settings(shadow_enabled=True, shadow_sample_rate=1)))
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider = FakeProvider()
    auditor = ShadowAuditor(redis, provider)
    try:
        assert auditor.maybe_schedule("question", "cached", "tenant-a")
        await asyncio.sleep(0)
        await auditor.aclose()
        assert not auditor._tasks
        assert not auditor.maybe_schedule("question", "cached", "tenant-a")
    finally:
        await redis.aclose()
        _runtime.reset(token)


@pytest.mark.asyncio
async def test_oversized_review_record_is_discarded():
    token = _runtime.set(
        snapshot(
            Settings(
                shadow_enabled=True,
                shadow_sample_rate=1,
                max_cache_entry_bytes=20,
            )
        )
    )
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider = FakeProvider()
    provider.release.set()
    auditor = ShadowAuditor(redis, provider)
    try:
        assert auditor.maybe_schedule("question", "cached", "tenant-a")
        await asyncio.gather(*auditor._tasks)
        assert await redis.keys("*:shadow:review:*") == []
    finally:
        await auditor.aclose()
        await redis.aclose()
        _runtime.reset(token)


@pytest.mark.asyncio
async def test_shadow_tenant_daily_budget_caps_provider_calls():
    token = _runtime.set(
        snapshot(
            Settings(
                shadow_enabled=True,
                shadow_sample_rate=1,
                shadow_daily_limit_per_tenant=1,
            )
        )
    )
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider = FakeProvider()
    provider.release.set()
    auditor = ShadowAuditor(redis, provider)
    try:
        for _ in range(2):
            assert auditor.maybe_schedule("question", "cached", "tenant-a")
            await asyncio.gather(*auditor._tasks)
        assert auditor.maybe_schedule("question", "cached", "tenant-b")
        await asyncio.gather(*auditor._tasks)
        assert provider.calls == TWO_TENANTS  # one allowed for each tenant
    finally:
        await auditor.aclose()
        await redis.aclose()
        _runtime.reset(token)


def test_chat_hit_schedules_shadow_without_changing_response(client):
    assert client.app.state.shadow_auditor.config.shadow_enabled
    assert client.app.state.shadow_auditor.config.shadow_sample_rate == 1.0
    query = {"prompt": "Explain the role of a cache key"}
    first = client.post("/v1/chat", json=query, headers=HEADERS)
    second = client.post("/v1/chat", json=query, headers=HEADERS)
    tasks = list(client.app.state.shadow_auditor._tasks)
    assert first.json()["cache"] == "MISS"
    assert second.json()["cache"] == "HIT"
    assert second.json()["answer"] == first.json()["answer"]

    async def read_records():
        if tasks:
            await asyncio.gather(*tasks)
        tenant = tenant_id(HEADERS["x-api-key"])
        key = f"{client.app.state.shadow_auditor.key_prefix}:shadow:review:{tenant}"
        return await client.app.state.redis.lrange(key, 0, -1)

    records = client.portal.call(read_records)
    assert len(tasks) == 1
    assert len(records) == 1
    assert json.loads(records[0])["review_status"] == "unreviewed"


test_chat_hit_schedules_shadow_without_changing_response.config_overrides = {
    "cache_match_mode": "exact",
    "shadow_enabled": True,
    "shadow_sample_rate": 1.0,
}
