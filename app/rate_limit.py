"""Token-bucket rate limiting, backed by Redis.

Two interchangeable implementations, chosen automatically:

* **Lua script (preferred, used on real Redis):** a single atomic server-side script —
  the textbook way to make a token bucket correct across many gateway replicas.
* **WATCH transaction (fallback):** optimistic-locking transaction with retry, used when
  the backend does not support server-side Lua (e.g. in-memory fakeredis during dev/tests).

Both are correct under concurrency; time is supplied from Python so behaviour matches.
"""
from __future__ import annotations

import time

import redis as redis_exc

from .config import settings
from .redis_client import get_redis

# KEYS[1] = bucket key; ARGV = capacity, refill_per_sec, now_ms, requested
_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity; ts = now end
local delta = math.max(0, now - ts) / 1000.0
tokens = math.min(capacity, tokens + delta * refill)
local allowed = 0
if tokens >= requested then tokens = tokens - requested; allowed = 1 end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil(capacity / refill * 1000) + 2000)
return {allowed, math.floor(tokens)}
"""


class RateLimiter:
    def __init__(self) -> None:
        self.capacity = float(settings.rate_limit_capacity)
        self.refill = float(settings.rate_limit_refill_per_sec)
        self._use_lua: bool | None = None  # decided lazily on first call

    def _ttl_ms(self) -> int:
        return int(self.capacity / self.refill * 1000) + 2000

    def _lua_supported(self, r) -> bool:
        try:
            r.eval("return 1", 0)
            return True
        except redis_exc.exceptions.ResponseError:
            return False

    def allow(self, api_key: str, cost: int = 1) -> tuple[bool, int]:
        r = get_redis()
        if self._use_lua is None:
            self._use_lua = self._lua_supported(r)
        now_ms = int(time.time() * 1000)
        key = f"ratelimit:{api_key}"
        if self._use_lua:
            allowed, remaining = r.eval(
                _LUA, 1, key, self.capacity, self.refill, now_ms, cost
            )
            return bool(allowed), int(remaining)
        return self._allow_txn(r, key, now_ms, cost)

    def _allow_txn(self, r, key: str, now_ms: int, cost: int) -> tuple[bool, int]:
        with r.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    data = pipe.hmget(key, "tokens", "ts")
                    tokens = float(data[0]) if data[0] is not None else self.capacity
                    ts = float(data[1]) if data[1] is not None else now_ms
                    delta = max(0, now_ms - ts) / 1000.0
                    tokens = min(self.capacity, tokens + delta * self.refill)
                    allowed = tokens >= cost
                    if allowed:
                        tokens -= cost
                    pipe.multi()
                    pipe.hset(key, mapping={"tokens": tokens, "ts": now_ms})
                    pipe.pexpire(key, self._ttl_ms())
                    pipe.execute()
                    return allowed, int(tokens)
                except redis_exc.exceptions.WatchError:
                    continue


rate_limiter = RateLimiter()
