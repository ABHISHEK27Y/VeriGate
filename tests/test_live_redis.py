"""Live Redis integration gates, including independent gateway processes."""

import json
import os
import subprocess
import sys
import uuid

import pytest

from app.config import settings

pytestmark = pytest.mark.skipif(not settings.redis_url, reason="requires disposable live Redis")

_CACHE_WORKER = """
import asyncio, json, sys
from app.cache.semantic_cache import SemanticCache
from app.cache import redisearch_store as rs
from app.config import settings
async def run():
    cache = SemanticCache()
    tenant, action = sys.argv[1:]
    try:
        if settings.cache_match_mode == 'semantic':
            await rs.ensure_index(len(cache.embedder.embed('probe')))
        if action == 'store':
            await cache.store('account recovery steps', 'verified answer', tenant)
        elif action == 'clear':
            await cache.clear(tenant)
        else:
            result = await cache.lookup('account recovery steps', tenant)
            print(json.dumps({'status': result.status, 'answer': result.answer}))
    finally:
        await cache.redis.aclose()
asyncio.run(run())
"""


@pytest.mark.parametrize("mode", ["exact", "semantic"])
def test_independent_worker_store_lookup_clear(mode):
    tenant = "integration_" + uuid.uuid4().hex
    env = {**os.environ, "CACHE_MATCH_MODE": mode, "EMBEDDING_BACKEND": "hash"}

    def worker(action):
        result = subprocess.run(
            [sys.executable, "-c", _CACHE_WORKER, tenant, action],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return json.loads(result.stdout) if action == "lookup" else None

    try:
        worker("store")
        hit = worker("lookup")
        assert hit == {"status": "HIT", "answer": "verified answer"}
        worker("clear")
        assert worker("lookup")["status"] == "MISS"
    finally:
        worker("clear")


def test_independent_workers_share_atomic_lua_bucket():
    key = "integration_" + uuid.uuid4().hex
    env = {**os.environ, "RATE_LIMIT_CAPACITY": "5", "RATE_LIMIT_REFILL_PER_SEC": "0.001"}
    source = """
import asyncio, sys
from app.rate_limit import RateLimiter
async def run():
    limiter = RateLimiter()
    try:
        results = await asyncio.gather(*(limiter.allow(sys.argv[1]) for _ in range(30)))
        assert limiter._use_lua is True
        print(sum(allowed for allowed, _ in results))
    finally:
        await limiter.redis.aclose()
asyncio.run(run())
"""
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", source, key],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        counts = []
        for worker in workers:
            output, error = worker.communicate(timeout=60)
            assert worker.returncode == 0, error
            counts.append(int(output))
        assert sum(counts) == 5  # noqa: PLR2004
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait()


@pytest.mark.asyncio
async def test_existing_vector_schema_mismatch_fails_closed():
    from app.cache import redisearch_store as rs  # noqa: PLC0415

    await rs.ensure_index(settings.embedding_dim)
    with pytest.raises(RuntimeError, match="Incompatible"):
        await rs.validate_index(settings.embedding_dim + 1)
    assert await rs.redisearch_available()


_SCOPED_QUOTA_WORKER = """
import asyncio, json, sys
from app.cache import storage
from app.redis_client import create_redis
async def run():
    tenant, action = sys.argv[1:]
    r = create_redis()
    try:
        if action in {'a', 'b', 'c'}:
            await storage.put(r, tenant, action, {'query': action, 'answer': action})
        elif action == 'touch-a':
            await storage.touch(r, tenant, 'a')
        elif action == 'inspect':
            _, _, prefix = storage.keys(tenant)
            values = [bool(await r.exists(prefix + eid)) for eid in ('a', 'b', 'c')]
            print(json.dumps({'live': values, 'occupancy': await storage.occupancy(r, tenant)}))
        elif action == 'clear':
            await storage.clear(r, tenant)
    finally:
        await r.aclose()
asyncio.run(run())
"""


def test_scoped_quota_and_hit_recency_across_worker_processes():
    tenant = "s_" + uuid.uuid4().hex[:16] + "_workers"
    env = {
        **os.environ,
        "SHARED_CACHE_ENTRY_LIMIT": "2",
        "ORGANIZATION_CACHE_ENTRY_LIMIT": "2",
    }

    def worker(action):
        result = subprocess.run(
            [sys.executable, "-c", _SCOPED_QUOTA_WORKER, tenant, action],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return json.loads(result.stdout) if action == "inspect" else None

    try:
        worker("a")
        worker("b")
        worker("touch-a")
        worker("c")
        observed = worker("inspect")
        assert observed["live"] == [True, False, True]
        assert observed["occupancy"]["entries"] == 2  # noqa: PLR2004
        assert observed["occupancy"]["evictions"] == 1
    finally:
        worker("clear")
