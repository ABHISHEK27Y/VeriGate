"""Token-bucket rate limiting, backed by Redis (async).

Two interchangeable implementations, chosen automatically:

* **Lua script (preferred, used on real Redis):** a single atomic server-side script —
  the textbook way to make a token bucket correct across many gateway replicas.
* **WATCH transaction (fallback):** optimistic-locking transaction with retry, used when
  the backend does not support server-side Lua (e.g. in-memory fakeredis during dev/tests).

The real Redis path uses server time; the test fallback clamps backward clock movement.
"""

from __future__ import annotations

import time

import redis.asyncio as redis
import redis.exceptions as redis_exc

from .config import get_settings
from .identity import hash_api_key
from .redis_client import create_redis

_RedisClient = redis.Redis

# KEYS[1] = bucket key; ARGV = capacity, refill_per_sec, now_ms, requested
_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local clock = redis.call("TIME")
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
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
    def __init__(self, redis_client=None) -> None:
        self.redis = redis_client if redis_client is not None else create_redis()
        self.capacity = float(get_settings().rate_limit_capacity)
        self.refill = float(get_settings().rate_limit_refill_per_sec)
        self._script = self.redis.register_script(_LUA)
        self._use_lua: bool | None = None  # decided lazily on first call

    def _ttl_ms(self) -> int:
        return int(self.capacity / self.refill * 1000) + 2000

    async def _lua_supported(self, r: _RedisClient) -> bool:
        try:
            await r.eval("return 1", 0)  # type: ignore[misc]
        except redis_exc.ResponseError:
            return False
        else:
            return True

    async def allow(self, api_key: str, cost: int = 1) -> tuple[bool, int]:
        r: _RedisClient = self.redis
        if self._use_lua is None:
            self._use_lua = await self._lua_supported(r)  # type: ignore[misc]
        now_ms = int(time.time() * 1000)
        key = f"ratelimit:{hash_api_key(api_key)}"
        if self._use_lua:
            result = await self._script(
                keys=[key], args=[str(self.capacity), str(self.refill), str(now_ms), str(cost)]
            )
            allowed, remaining = result[0], result[1]
            return bool(int(allowed)), int(remaining)
        return await self._allow_txn(r, key, now_ms, cost)  # type: ignore[misc]

    async def _allow_txn(
        self, r: _RedisClient, key: str, now_ms: int, cost: int
    ) -> tuple[bool, int]:
        for _ in range(100):
            try:
                async with r.pipeline(transaction=True) as pipe:
                    await pipe.watch(key)  # type: ignore[misc]
                    data = await pipe.hmget(key, ["tokens", "ts"])  # type: ignore[misc]
                    tokens = float(data[0]) if data[0] is not None else self.capacity
                    ts = float(data[1]) if data[1] is not None else now_ms
                    now_ms = max(now_ms, int(ts))
                    delta = (now_ms - ts) / 1000.0
                    tokens = min(self.capacity, tokens + delta * self.refill)
                    allowed = tokens >= cost
                    if allowed:
                        tokens -= cost
                    pipe.multi()
                    pipe.hset(key, mapping={"tokens": tokens, "ts": now_ms})
                    pipe.pexpire(key, self._ttl_ms())
                    await pipe.execute()  # type: ignore[misc]
                    return allowed, int(tokens)
            except redis_exc.WatchError:
                continue
        return False, 0
