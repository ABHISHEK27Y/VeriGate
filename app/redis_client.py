"""Redis connection (async).

If REDIS_URL is set  -> connect to a real Redis server via redis.asyncio.
If REDIS_URL is blank -> use fakeredis.aioredis (async in-memory Redis).
Same code path either way.
"""

from __future__ import annotations

import logging

from .config import settings

log = logging.getLogger("verigate.redis")

_client = None


async def get_redis():
    """Return a singleton async Redis client (real or fake)."""
    global _client
    if _client is not None:
        return _client

    if settings.redis_url:
        import redis.asyncio as redis

        _client = redis.from_url(settings.redis_url, decode_responses=True)
        log.info("Using REAL Redis at %s", settings.redis_url)
    else:
        import fakeredis.aioredis

        _client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        log.info("Using in-memory fakeredis (set REDIS_URL to use a real server).")

    return _client


def redis_backend_name() -> str:
    return "real-redis" if settings.redis_url else "fakeredis (in-memory)"


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
