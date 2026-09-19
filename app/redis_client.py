"""Redis connection.

If REDIS_URL is set  -> connect to a real Redis server.
If REDIS_URL is blank -> use fakeredis (a real Redis implementation that runs
                         in-process, in memory). Nothing to install, perfect for
                         development and tests. Same code path either way.
"""
from __future__ import annotations

import logging

from .config import settings

log = logging.getLogger("verigate.redis")

_client = None


def get_redis():
    """Return a singleton Redis client (real or fake)."""
    global _client
    if _client is not None:
        return _client

    if settings.redis_url:
        import redis

        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        log.info("Using REAL Redis at %s", settings.redis_url)
    else:
        import fakeredis

        _client = fakeredis.FakeStrictRedis(decode_responses=True)
        log.info("Using in-memory fakeredis (set REDIS_URL to use a real server).")

    return _client


def redis_backend_name() -> str:
    return "real-redis" if settings.redis_url else "fakeredis (in-memory)"
