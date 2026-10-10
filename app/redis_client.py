"""Application-owned async Redis connections."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import cast

import fakeredis.aioredis
import redis.asyncio as redis
from fastapi import Request

from .config import get_settings


def create_redis(*, binary: bool = False) -> redis.Redis:
    """Caller owns and closes this connection on its originating event loop."""
    if get_settings().redis_url:
        return cast(
            redis.Redis,
            redis.from_url(
                get_settings().redis_url,
                decode_responses=not binary,
                socket_connect_timeout=5,
                socket_timeout=5,
                max_connections=100,
            ),
        )
    return fakeredis.aioredis.FakeRedis(decode_responses=not binary)


async def get_redis(request: Request) -> redis.Redis:
    return cast(redis.Redis, request.app.state.redis)


def redis_backend_name() -> str:
    return "real-redis" if get_settings().redis_url else "fakeredis (in-memory)"


async def close_redis(client: redis.Redis) -> None:
    await client.aclose()


async def hash_fields(client: redis.Redis, key: str) -> dict[str, str]:
    """Adapt redis-py's shared sync/async annotation at the client boundary."""
    return await cast(Awaitable[dict[str, str]], client.hgetall(key))


async def set_members(client: redis.Redis, key: str) -> set[str]:
    return await cast(Awaitable[set[str]], client.smembers(key))


async def remove_member(client: redis.Redis, key: str, member: str) -> int:
    return await cast(Awaitable[int], client.srem(key, member))
