"""Atomic cache membership, TTL, and eviction shared by both storage backends."""

from __future__ import annotations

import time
import uuid

from redis.exceptions import WatchError

from ..config import get_settings
from .namespace import namespace as current_namespace


def keys(tenant: str, namespace: str | None = None) -> tuple[str, str, str]:
    namespace = namespace or current_namespace()
    return f"{namespace}:ids:{tenant}", f"{namespace}:lru:{tenant}", f"{namespace}:entry:{tenant}:"


async def put(r, tenant: str, eid: str, mapping: dict, namespace: str | None = None) -> None:
    size = sum(
        len(value if isinstance(value, bytes) else str(value).encode("utf-8"))
        for value in mapping.values()
    )
    if size > get_settings().max_cache_entry_bytes:
        return
    namespace = namespace or current_namespace()
    ids, lru, prefix = keys(tenant, namespace)
    for _ in range(100):
        try:
            async with r.pipeline(transaction=True) as pipe:
                await pipe.watch(ids, lru)
                count = await pipe.zcard(lru)
                existing = await pipe.zscore(lru, eid)
                limit = get_settings().max_cache_entries_per_tenant
                excess = max(0, count + (existing is None) - limit)
                victims = await pipe.zrange(lru, 0, excess - 1) if excess else []
                pipe.multi()
                pipe.set(
                    f"{namespace}:version:{tenant}",
                    uuid.uuid4().hex,
                    ex=get_settings().cache_ttl_sec,
                )
                pipe.hset(prefix + eid, mapping=mapping)
                if get_settings().cache_ttl_sec > 0:
                    pipe.expire(prefix + eid, get_settings().cache_ttl_sec)
                    pipe.expire(ids, get_settings().cache_ttl_sec)
                    pipe.expire(lru, get_settings().cache_ttl_sec)
                pipe.sadd(ids, eid)
                pipe.zadd(lru, {eid: time.time()})
                # Expire metadata after creating it, including the first write.
                if get_settings().cache_ttl_sec > 0:
                    pipe.expire(ids, get_settings().cache_ttl_sec)
                    pipe.expire(lru, get_settings().cache_ttl_sec)
                for victim in victims:
                    value = victim.decode() if isinstance(victim, bytes) else victim
                    pipe.delete(prefix + value)
                    pipe.srem(ids, victim)
                    pipe.zrem(lru, victim)
                await pipe.execute()
                return
        except WatchError:
            continue
    raise RuntimeError("Cache write contention exceeded retry limit")


async def clear(r, tenant: str, namespace: str | None = None) -> None:
    namespace = namespace or current_namespace()
    ids, lru, prefix = keys(tenant, namespace)
    for _ in range(100):
        try:
            async with r.pipeline(transaction=True) as pipe:
                await pipe.watch(ids, lru)
                members = await pipe.smembers(ids)
                pipe.multi()
                pipe.set(
                    f"{namespace}:version:{tenant}",
                    uuid.uuid4().hex,
                    ex=get_settings().cache_ttl_sec,
                )
                for member in members:
                    value = member.decode() if isinstance(member, bytes) else member
                    pipe.delete(prefix + value)
                pipe.delete(ids, lru)
                await pipe.execute()
                return
        except WatchError:
            continue
    raise RuntimeError("Cache clear contention exceeded retry limit")
