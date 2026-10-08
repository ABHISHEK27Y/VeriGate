"""Provider circuit breaker (reliability).

Tracks failures per provider in Redis. After `breaker_fail_threshold` failures within
`breaker_window_sec`, the breaker OPENS and the router skips that provider for
`breaker_cooldown_sec` (fail fast instead of hammering a dead upstream). A success resets the
count. State lives in Redis so all gateway replicas agree.
"""
from __future__ import annotations

from ..config import settings
from ..redis_client import get_redis


def _open_key(name: str) -> str:
    return f"breaker:open:{name}"


def _fail_key(name: str) -> str:
    return f"breaker:fails:{name}"


async def is_open(name: str) -> bool:
    try:
        r = await get_redis()
        return bool(await r.exists(_open_key(name)))
    except Exception:
        return False


async def record_failure(name: str) -> None:
    r = await get_redis()
    k = _fail_key(name)
    n = int(await r.incr(k))
    if n == 1:
        await r.expire(k, settings.breaker_window_sec)
    if n >= settings.breaker_fail_threshold:
        await r.set(_open_key(name), "1", ex=settings.breaker_cooldown_sec)
        await r.delete(k)


async def record_success(name: str) -> None:
    r = await get_redis()
    await r.delete(_fail_key(name))
    await r.delete(_open_key(name))