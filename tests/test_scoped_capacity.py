"""Redis transactions enforce shared/private and organization quotas."""

from __future__ import annotations

import asyncio
import hashlib

import fakeredis.aioredis
import numpy as np
import pytest

from app.cache import storage
from app.cache.semantic_cache import SemanticCache
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


@pytest.mark.asyncio
async def test_expired_recently_touched_entry_does_not_evict_live_entry() -> None:
    config = Settings(
        _env_file=None,
        shared_cache_entry_limit=2,
        organization_cache_entry_limit=2,
    )
    token = _runtime.set(config)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant = "s_dddddddddddddddd_engineering"
    try:
        assert await storage.put(r, tenant, "expired", {"query": "old", "answer": "old"})
        assert await storage.put(r, tenant, "live", {"query": "live", "answer": "live"})
        await storage.touch(r, tenant, "expired")
        namespace = storage.current_namespace()
        await r.zadd(storage._org_expiry(tenant, namespace), {f"{tenant}|expired": 1})
        await r.delete(storage.keys(tenant)[2] + "expired")
        assert await storage.put(r, tenant, "new", {"query": "new", "answer": "new"})
        assert await r.exists(storage.keys(tenant)[2] + "live") == 1
        assert await r.exists(storage.keys(tenant)[2] + "new") == 1
        assert await r.zscore(storage._org_keys(tenant, namespace)[0], f"{tenant}|expired") is None
        assert (await storage.occupancy(r, tenant))["entries"] == SCOPE_LIMIT
        assert (await storage.occupancy(r, tenant))["evictions"] == 0
        expected = sum(
            sum(len(str(value).encode()) for value in row.values())
            for row in ({"query": "live", "answer": "live"}, {"query": "new", "answer": "new"})
        )
        assert int(await r.get(f"{namespace}:bytes:{tenant}")) == expected
    finally:
        _runtime.reset(token)
        await r.aclose()


@pytest.mark.asyncio
async def test_index_rebuild_leaves_expired_quota_metadata_for_atomic_cleanup() -> None:
    class FixedEmbedder:
        def embed(self, _query):
            return np.array([1.0, 0.0], dtype=np.float32)

    config = Settings(
        _env_file=None,
        cache_match_mode="semantic",
        vector_backend="inproc",
        shared_cache_entry_limit=2,
        organization_cache_entry_limit=4,
    )
    token = _runtime.set(config)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant = "s_eeeeeeeeeeeeeeee_engineering"
    try:
        cache = SemanticCache(r, FixedEmbedder())
        assert await cache.store("old question", "old answer", tenant)
        assert await cache.store("second question", "second answer", tenant)
        ids, lru, prefix = storage.keys(tenant)
        old = hashlib.sha256(b"old question").hexdigest()
        await r.delete(prefix + old)
        await cache._build_index(tenant)
        # Index rebuilding must not partially mutate quota metadata.
        assert old in await r.smembers(ids)
        assert await r.zscore(lru, old) is not None
        assert await cache.store("third question", "third answer", tenant)
        assert old not in await r.smembers(ids)
        assert await r.zscore(lru, old) is None
        assert (await storage.occupancy(r, tenant))["entries"] == SCOPE_LIMIT
    finally:
        _runtime.reset(token)
        await r.aclose()


@pytest.mark.asyncio
async def test_old_expiry_score_never_deletes_live_hash() -> None:
    config = Settings(_env_file=None, shared_cache_entry_limit=2, organization_cache_entry_limit=3)
    token = _runtime.set(config)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant = "s_ffffffffffffffff_engineering"
    try:
        assert await storage.put(r, tenant, "old", {"query": "old", "answer": "old"})
        namespace = storage.current_namespace()
        await r.zadd(storage._org_expiry(tenant, namespace), {f"{tenant}|old": 1})
        assert await r.ttl(storage.keys(tenant)[2] + "old") > 0
        assert await storage.put(r, tenant, "new", {"query": "new", "answer": "new"})
        assert await r.exists(storage.keys(tenant)[2] + "old") == 1
        assert (await storage.occupancy(r, tenant))["entries"] == SCOPE_LIMIT
    finally:
        _runtime.reset(token)
        await r.aclose()
