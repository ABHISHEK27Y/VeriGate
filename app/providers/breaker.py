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


def is_open(name: str) -> bool:
    try:
        return bool(get_redis().exists(_open_key(name)))
    except Exception:
        return False


def record_failure(name: str) -> None:
    r = get_redis()
    k = _fail_key(name)
    n = int(r.incr(k))
    if n == 1:
        r.expire(k, settings.breaker_window_sec)
    if n >= settings.breaker_fail_threshold:
        r.set(_open_key(name), "1", ex=settings.breaker_cooldown_sec)
        r.delete(k)


def record_success(name: str) -> None:
    r = get_redis()
    r.delete(_fail_key(name))
    r.delete(_open_key(name))
