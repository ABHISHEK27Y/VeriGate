"""Atomic cache membership, TTL, and eviction shared by both storage backends."""

from __future__ import annotations

import time
import uuid

from redis.exceptions import ResponseError, WatchError

from ..config import get_settings
from .namespace import namespace as current_namespace

_SCOPED_PARTS = 3
_EXPIRY_RECONCILE_BATCH = 256


def keys(tenant: str, namespace: str | None = None) -> tuple[str, str, str]:
    namespace = namespace or current_namespace()
    return f"{namespace}:ids:{tenant}", f"{namespace}:lru:{tenant}", f"{namespace}:entry:{tenant}:"


def _scoped(tenant: str) -> bool:
    return tenant.startswith(("s_", "p_")) and len(tenant.split("_", 2)) == _SCOPED_PARTS


def _org_keys(tenant: str, namespace: str) -> tuple[str, str, str]:
    organization = tenant.split("_", 2)[1]
    prefix = f"{namespace}:org:{organization}"
    return f"{prefix}:lru", f"{prefix}:sizes", f"{prefix}:bytes"


def _org_expiry(tenant: str, namespace: str) -> str:
    return f"{namespace}:org:{tenant.split('_', 2)[1]}:expires"


def _limits(tenant: str) -> tuple[int, int]:
    config = get_settings()
    if tenant.startswith("s_"):
        return config.shared_cache_entry_limit, config.shared_cache_byte_limit
    return config.private_cache_entry_limit, config.private_cache_byte_limit


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else value


async def _put_scoped(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917 - atomic quota transaction
    r, tenant: str, eid: str, mapping: dict, size: int, namespace: str
) -> bool:
    config = get_settings()
    count_limit, byte_limit = _limits(tenant)
    if size > min(byte_limit, config.organization_cache_byte_limit):
        return False
    ids, lru, prefix = keys(tenant, namespace)
    sizes, bytes_key = f"{namespace}:sizes:{tenant}", f"{namespace}:bytes:{tenant}"
    org_lru, org_sizes, org_bytes = _org_keys(tenant, namespace)
    org_expires = _org_expiry(tenant, namespace)
    member = f"{tenant}|{eid}"
    ttl = config.cache_ttl_sec
    for _ in range(100):
        try:
            async with r.pipeline(transaction=True) as pipe:
                await pipe.watch(
                    ids, lru, sizes, bytes_key, org_lru, org_sizes, org_bytes, org_expires
                )
                redis_clock = await pipe.time()
                redis_now = float(redis_clock[0]) + float(redis_clock[1]) / 1_000_000
                expired_candidates = [
                    _text(value)
                    for value in await pipe.zrangebyscore(
                        org_expires, "-inf", redis_now, start=0, num=_EXPIRY_RECONCILE_BATCH
                    )
                ]
                more_stale = len(expired_candidates) == _EXPIRY_RECONCILE_BATCH
                candidate_keys = [
                    keys(candidate.rsplit("|", 1)[0], namespace)[2] + candidate.rsplit("|", 1)[1]
                    for candidate in expired_candidates
                ]
                if candidate_keys:
                    await pipe.watch(*candidate_keys)
                candidate_ttls = [await pipe.pttl(key) for key in candidate_keys]
                stale = [
                    candidate
                    for candidate, remaining in zip(expired_candidates, candidate_ttls, strict=True)
                    if remaining <= 0
                ]
                live_expiry = {
                    candidate: redis_now + remaining / 1000
                    for candidate, remaining in zip(expired_candidates, candidate_ttls, strict=True)
                    if remaining > 0
                }
                stale_sizes = {
                    member: int(float(await pipe.zscore(org_sizes, member) or 0))
                    for member in stale
                }
                stale_org_count = sum(
                    [await pipe.zscore(org_lru, candidate) is not None for candidate in stale]
                )
                existing_size = float(await pipe.zscore(sizes, eid) or 0)
                existed = await pipe.zscore(lru, eid) is not None and member not in stale_sizes
                if member in stale_sizes:
                    existing_size = 0
                stale_here = [
                    (
                        member.rsplit("|", 1)[1],
                        await pipe.zscore(lru, member.rsplit("|", 1)[1]) is not None,
                        int(float(await pipe.zscore(sizes, member.rsplit("|", 1)[1]) or 0)),
                    )
                    for member in stale_sizes
                    if member.startswith(f"{tenant}|")
                ]
                scope_count = (
                    int(await pipe.zcard(lru))
                    - sum(present for _, present, _ in stale_here)
                    + (not existed)
                )
                scope_bytes = (
                    int(await pipe.get(bytes_key) or 0)
                    - sum(amount for _, _, amount in stale_here)
                    - int(existing_size)
                    + size
                )
                org_count = int(await pipe.zcard(org_lru)) - stale_org_count + (not existed)
                org_total = (
                    int(await pipe.get(org_bytes) or 0)
                    - sum(stale_sizes.values())
                    - int(existing_size)
                    + size
                )
                victims: list[tuple[str, str, int]] = [
                    (member.rsplit("|", 1)[0], member.rsplit("|", 1)[1], amount)
                    for member, amount in stale_sizes.items()
                ]
                selected: set[str] = set(stale)
                if more_stale:
                    # Clean one bounded batch atomically, then retry quota selection.
                    affected = {scope for scope, _, _ in victims}
                    for other in affected - {tenant}:
                        await pipe.watch(
                            f"{namespace}:ids:{other}",
                            f"{namespace}:lru:{other}",
                            f"{namespace}:sizes:{other}",
                            f"{namespace}:bytes:{other}",
                        )
                    remaining = {
                        other: (
                            int(await pipe.get(f"{namespace}:bytes:{other}") or 0)
                            - sum(amount for scope, _, amount in victims if scope == other)
                        )
                        for other in affected
                    }
                    remaining_org = int(await pipe.get(org_bytes) or 0) - sum(stale_sizes.values())
                    if remaining_org < 0 or any(value < 0 for value in remaining.values()):
                        raise RuntimeError("Cache byte metadata is inconsistent")
                    pipe.multi()
                    if live_expiry:
                        pipe.zadd(org_expires, live_expiry)
                    for other, victim, _amount in victims:
                        victim_ids, victim_lru, victim_prefix = keys(other, namespace)
                        pipe.delete(victim_prefix + victim)
                        pipe.srem(victim_ids, victim)
                        pipe.zrem(victim_lru, victim)
                        pipe.zrem(f"{namespace}:sizes:{other}", victim)
                        pipe.zrem(org_lru, f"{other}|{victim}")
                        pipe.zrem(org_sizes, f"{other}|{victim}")
                        pipe.zrem(org_expires, f"{other}|{victim}")
                    for other, total in remaining.items():
                        pipe.set(f"{namespace}:bytes:{other}", total, ex=ttl)
                        pipe.set(f"{namespace}:version:{other}", uuid.uuid4().hex, ex=ttl)
                    pipe.set(org_bytes, remaining_org, ex=ttl)
                    await pipe.execute()
                    continue
                scope_candidates = (
                    await pipe.zrange(lru, 0, -1)
                    if not more_stale and (scope_count > count_limit or scope_bytes > byte_limit)
                    else []
                )
                for candidate in scope_candidates:
                    victim = _text(candidate)
                    if scope_count <= count_limit and scope_bytes <= byte_limit:
                        break
                    if victim == eid or f"{tenant}|{victim}" in selected:
                        continue
                    victim_size = int(float(await pipe.zscore(sizes, victim) or 0))
                    victims.append((tenant, victim, victim_size))
                    selected.add(f"{tenant}|{victim}")
                    scope_count -= 1
                    scope_bytes -= victim_size
                    org_count -= 1
                    org_total -= victim_size
                org_candidates = (
                    await pipe.zrange(org_lru, 0, -1)
                    if not more_stale
                    and (
                        org_count > config.organization_cache_entry_limit
                        or org_total > config.organization_cache_byte_limit
                    )
                    else []
                )
                for candidate in org_candidates:
                    if (
                        org_count <= config.organization_cache_entry_limit
                        and org_total <= config.organization_cache_byte_limit
                    ):
                        break
                    org_member = _text(candidate)
                    if org_member == member or org_member in selected:
                        continue
                    victim_tenant, victim = org_member.rsplit("|", 1)
                    victim_size = int(float(await pipe.zscore(org_sizes, org_member) or 0))
                    victims.append((victim_tenant, victim, victim_size))
                    selected.add(org_member)
                    org_count -= 1
                    org_total -= victim_size
                    if victim_tenant == tenant:
                        scope_count -= 1
                        scope_bytes -= victim_size
                if not more_stale and (
                    scope_count > count_limit
                    or scope_bytes > byte_limit
                    or org_count > config.organization_cache_entry_limit
                    or org_total > config.organization_cache_byte_limit
                ):
                    return False
                for victim_tenant, _, _ in victims:
                    if victim_tenant != tenant:
                        await pipe.watch(
                            f"{namespace}:ids:{victim_tenant}",
                            f"{namespace}:lru:{victim_tenant}",
                            f"{namespace}:sizes:{victim_tenant}",
                            f"{namespace}:bytes:{victim_tenant}",
                        )
                other_bytes = {
                    victim_tenant: (
                        int(await pipe.get(f"{namespace}:bytes:{victim_tenant}") or 0)
                        - sum(size for scope, _, size in victims if scope == victim_tenant)
                    )
                    for victim_tenant, _, _ in victims
                    if victim_tenant != tenant
                }
                if any(value < 0 for value in other_bytes.values()):
                    raise RuntimeError("Cache byte metadata is inconsistent")
                pipe.multi()
                if live_expiry:
                    pipe.zadd(org_expires, live_expiry)
                for victim_tenant, victim, _victim_size in victims:
                    victim_ids, victim_lru, victim_prefix = keys(victim_tenant, namespace)
                    pipe.delete(victim_prefix + victim)
                    pipe.srem(victim_ids, victim)
                    pipe.zrem(victim_lru, victim)
                    pipe.zrem(f"{namespace}:sizes:{victim_tenant}", victim)
                    pipe.zrem(org_lru, f"{victim_tenant}|{victim}")
                    pipe.zrem(org_sizes, f"{victim_tenant}|{victim}")
                    pipe.zrem(org_expires, f"{victim_tenant}|{victim}")
                    if victim_tenant != tenant:
                        pipe.set(f"{namespace}:version:{victim_tenant}", uuid.uuid4().hex, ex=ttl)
                for victim_tenant, remaining_bytes in other_bytes.items():
                    pipe.set(f"{namespace}:bytes:{victim_tenant}", remaining_bytes, ex=ttl)
                evicted = [
                    (scope, victim)
                    for scope, victim, _amount in victims
                    if f"{scope}|{victim}" not in stale_sizes
                ]
                for victim_tenant in {scope for scope, _victim in evicted}:
                    pipe.incrby(
                        f"{namespace}:evictions:{victim_tenant}",
                        sum(scope == victim_tenant for scope, _victim in evicted),
                    )
                    pipe.expire(f"{namespace}:evictions:{victim_tenant}", ttl)
                pipe.hset(prefix + eid, mapping=mapping)
                pipe.expire(prefix + eid, ttl)
                pipe.sadd(ids, eid)
                pipe.zadd(lru, {eid: redis_now})
                pipe.zadd(sizes, {eid: size})
                pipe.zadd(org_lru, {member: redis_now})
                pipe.zadd(org_sizes, {member: size})
                pipe.zadd(org_expires, {member: redis_now + ttl})
                if scope_bytes < 0 or org_total < 0:
                    raise RuntimeError("Cache byte metadata is inconsistent")
                pipe.set(bytes_key, scope_bytes, ex=ttl)
                pipe.set(org_bytes, org_total, ex=ttl)
                pipe.set(f"{namespace}:version:{tenant}", uuid.uuid4().hex, ex=ttl)
                for metadata in (ids, lru, sizes, org_lru, org_sizes, org_expires):
                    pipe.expire(metadata, ttl)
                await pipe.execute()
                return True
        except WatchError:
            continue
    raise RuntimeError("Scoped cache write contention exceeded retry limit")


async def put(r, tenant: str, eid: str, mapping: dict, namespace: str | None = None) -> bool:
    size = sum(
        len(value if isinstance(value, bytes) else str(value).encode("utf-8"))
        for value in mapping.values()
    )
    if size > get_settings().max_cache_entry_bytes:
        return False
    namespace = namespace or current_namespace()
    if _scoped(tenant):
        return await _put_scoped(r, tenant, eid, mapping, size, namespace)
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
                return True
        except WatchError:
            continue
    raise RuntimeError("Cache write contention exceeded retry limit")


async def touch(r, tenant: str, eid: str, namespace: str | None = None) -> None:
    """Refresh recency only for a served hit, in both scoped quota indexes."""
    namespace = namespace or current_namespace()
    _, lru, _ = keys(tenant, namespace)
    score = time.time()
    async with r.pipeline(transaction=True) as pipe:
        pipe.zadd(lru, {eid: score}, xx=True)
        if _scoped(tenant):
            org_lru, _, _ = _org_keys(tenant, namespace)
            pipe.zadd(org_lru, {f"{tenant}|{eid}": score}, xx=True)
        await pipe.execute()


async def clear(r, tenant: str, namespace: str | None = None) -> None:
    namespace = namespace or current_namespace()
    if _scoped(tenant):
        await _clear_scoped(r, tenant, namespace)
        return
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


async def _clear_scoped(r, tenant: str, namespace: str) -> None:
    ids, lru, prefix = keys(tenant, namespace)
    sizes, bytes_key = f"{namespace}:sizes:{tenant}", f"{namespace}:bytes:{tenant}"
    org_lru, org_sizes, org_bytes = _org_keys(tenant, namespace)
    org_expires = _org_expiry(tenant, namespace)
    for _ in range(100):
        try:
            async with r.pipeline(transaction=True) as pipe:
                await pipe.watch(
                    ids, lru, sizes, bytes_key, org_lru, org_sizes, org_bytes, org_expires
                )
                members = await pipe.smembers(ids)
                org_members = [
                    _text(value)
                    for value in await pipe.zrange(org_lru, 0, -1)
                    if _text(value).startswith(f"{tenant}|")
                ]
                used = 0
                for member in org_members:
                    used += int(float(await pipe.zscore(org_sizes, member) or 0))
                org_total = max(0, int(await pipe.get(org_bytes) or 0) - used)
                pipe.multi()
                for member in members:
                    pipe.delete(prefix + _text(member))
                pipe.delete(ids, lru, sizes, bytes_key)
                for member in org_members:
                    pipe.zrem(org_lru, member)
                    pipe.zrem(org_sizes, member)
                    pipe.zrem(org_expires, member)
                pipe.set(org_bytes, org_total, ex=get_settings().cache_ttl_sec)
                pipe.set(
                    f"{namespace}:version:{tenant}",
                    uuid.uuid4().hex,
                    ex=get_settings().cache_ttl_sec,
                )
                await pipe.execute()
                return
        except WatchError:
            continue
    raise RuntimeError("Scoped cache clear contention exceeded retry limit")


async def occupancy(r, tenant: str, namespace: str | None = None) -> dict[str, int]:
    """Count live entries and Redis memory without revealing cached content."""
    namespace = namespace or current_namespace()
    ids, _, prefix = keys(tenant, namespace)
    members = await r.smembers(ids)
    count = 0
    redis_bytes = 0
    estimated_entries = 0
    earliest_ttl = 0
    for member in members:
        key = prefix + _text(member)
        if not await r.exists(key):
            continue
        count += 1
        try:
            size = await r.memory_usage(key)
        except ResponseError:
            row = await r.hgetall(key)
            size = sum(len(str(value).encode()) for value in row.values())
            estimated_entries += 1
        redis_bytes += int(size or 0)
        ttl = int(await r.ttl(key))
        if ttl > 0:
            earliest_ttl = ttl if earliest_ttl == 0 else min(earliest_ttl, ttl)
    evictions = int(await r.get(f"{namespace}:evictions:{tenant}") or 0)
    return {
        "entries": count,
        "redis_entry_bytes": redis_bytes,
        "estimated_entries": estimated_entries,
        "stale_memberships": len(members) - count,
        "earliest_expiry_seconds": earliest_ttl,
        "evictions": evictions,
    }
