"""Redis transactions enforce shared/private and organization quotas."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from app.cache import storage
from app.config import Settings, _runtime

SCOPE_LIMIT = 2
ORG_LIMIT = 3


@pytest.mark.asyncio
async def test_scope_and_organization_quota_across_clients() -> None:
    config = Settings(
        _env_file=None,
        shared_cache_entry_limit=2,
        private_cache_entry_limit=2,
        organization_cache_entry_limit=3,
        shared_cache_byte_limit=10000,
        private_cache_byte_limit=10000,
        organization_cache_byte_limit=20000,
    )
    token = _runtime.set(config)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    shared, private = "s_aaaaaaaaaaaaaaaa_workspace", "p_aaaaaaaaaaaaaaaa_employee"
    try:

        async def put(tenant: str, number: int) -> bool:
            return await storage.put(
                r,
                tenant,
                str(number),
                {"query": f"technical question {number}", "answer": f"answer {number}"},
            )

        assert await put(shared, 1)
        assert await put(shared, 2)
        assert await put(shared, 3)
        assert await r.exists(storage.keys(shared)[2] + "1") == 0
        assert (await storage.occupancy(r, shared))["entries"] == SCOPE_LIMIT
        # Two independently scheduled workers write into the same Redis-backed org.
        assert all(await asyncio.gather(put(private, 4), put(private, 5)))
        totals = [await storage.occupancy(r, tenant) for tenant in (shared, private)]
        assert sum(item["entries"] for item in totals) == ORG_LIMIT
        assert (await storage.occupancy(r, private))["entries"] == SCOPE_LIMIT
        assert (await storage.occupancy(r, shared))["evictions"] >= SCOPE_LIMIT
    finally:
        _runtime.reset(token)
        await r.aclose()


@pytest.mark.asyncio
async def test_byte_limit_fails_closed_without_partial_write() -> None:
    config = Settings(_env_file=None, shared_cache_byte_limit=10)
    token = _runtime.set(config)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant = "s_bbbbbbbbbbbbbbbb_workspace"
    try:
        stored = await storage.put(
            r, tenant, "entry", {"query": "long technical query", "answer": "long answer"}
        )
        assert not stored
        assert (await storage.occupancy(r, tenant))["entries"] == 0
    finally:
        _runtime.reset(token)
        await r.aclose()


@pytest.mark.asyncio
async def test_served_hit_refreshes_scope_and_organization_lru() -> None:
    config = Settings(
        _env_file=None,
        shared_cache_entry_limit=2,
        organization_cache_entry_limit=2,
    )
    token = _runtime.set(config)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant = "s_cccccccccccccccc_engineering"
    try:
        for eid in ("old", "new"):
            assert await storage.put(r, tenant, eid, {"query": eid, "answer": eid})
        await storage.touch(r, tenant, "old")
        org_lru = storage._org_keys(tenant, storage.current_namespace())[0]
        assert (await r.zscore(org_lru, f"{tenant}|old")) >= (
            await r.zscore(org_lru, f"{tenant}|new")
        )
        assert await storage.put(r, tenant, "third", {"query": "third", "answer": "third"})
        assert await r.exists(storage.keys(tenant)[2] + "old") == 1
        assert await r.exists(storage.keys(tenant)[2] + "new") == 0
    finally:
        _runtime.reset(token)
        await r.aclose()
