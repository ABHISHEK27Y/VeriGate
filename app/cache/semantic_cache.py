"""The semantic cache: vector lookup + the three sub-contributions, PARTITIONED PER TENANT.

Every read and write is scoped to a `tenant` (derived from the caller's API key), so one
tenant's queries can never match another tenant's cached answers. This closes the most
serious risk of a shared semantic cache — cross-tenant data leakage (see docs/SECURITY.md #1).

Storage (Redis is the source of truth):
  cache:ids:<tenant>            -> SET of entry ids for that tenant
  cache:entry:<tenant>:<id>     -> HASH {query, answer, vec(csv), ts}
  cache:lru:<tenant>            -> ZSET {eid: timestamp} for LRU eviction

Lookup uses a per-tenant in-process vectorised index (one NumPy matrix per tenant), or the
shared RediSearch HNSW index filtered by a tenant TAG when VECTOR_BACKEND=redisearch.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import numpy as np

from ..config import settings
from ..embeddings import embed
from ..redis_client import get_redis
from .policy import CachePolicy
from .volatility import is_volatile


@dataclass(slots=True, frozen=True)
class LookupResult:
    status: str            # HIT | MISS | BYPASS
    answer: str | None = None
    threshold: float | None = None
    similarity: float | None = None
    reason: str | None = None


class SemanticCache:
    """Async semantic cache with per-tenant isolation and LRU eviction."""

    def __init__(self) -> None:
        # in-process vectorised index, keyed by tenant
        self._index: dict[str, dict] = {}
        self._policy = CachePolicy(
            static_threshold=settings.cache_similarity_base,
            use_nli=settings.verifier_nli,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _ids_key(self, tenant: str) -> str:
        return f"cache:ids:{tenant}"

    def _entry_key(self, tenant: str, eid: str) -> str:
        return f"cache:entry:{tenant}:{eid}"

    def _lru_key(self, tenant: str) -> str:
        return f"cache:lru:{tenant}"

    def _vec_to_str(self, v: np.ndarray) -> str:
        return ",".join(f"{x:.6f}" for x in v.tolist())

    def _str_to_vec(self, s: str) -> np.ndarray:
        return np.array([float(x) for x in s.split(",") if x], dtype=np.float32)

    def _t(self, tenant: str) -> dict:
        return self._index.setdefault(
            tenant, {"ids": [], "queries": [], "answers": [], "mat": None, "built": False}
        )

    async def _build_index(self, tenant: str) -> None:
        t = self._t(tenant)
        t["ids"].clear()
        t["queries"].clear()
        t["answers"].clear()
        r = await get_redis()
        rows = []
        for eid in await r.smembers(self._ids_key(tenant)):
            d = await r.hgetall(self._entry_key(tenant, eid))
            if not d:
                await r.srem(self._ids_key(tenant), eid)   # entry expired (TTL): drop the dangling id
                continue
            t["ids"].append(eid)
            t["queries"].append(d["query"])
            t["answers"].append(d["answer"])
            rows.append(self._str_to_vec(d["vec"]))
        t["mat"] = np.vstack(rows).astype(np.float32) if rows else None
        t["built"] = True

    async def _ensure(self, tenant: str) -> None:
        if not self._t(tenant)["built"]:
            await self._build_index(tenant)

    def _append(self, tenant: str, eid: str, query: str, answer: str, vec: np.ndarray) -> None:
        t = self._t(tenant)
        t["ids"].append(eid)
        t["queries"].append(query)
        t["answers"].append(answer)
        row = vec.astype(np.float32)[None, :]
        t["mat"] = row if t["mat"] is None else np.vstack([t["mat"], row])

    def _evict_from_index(self, tenant: str, eid: str) -> None:
        """Remove an entry from the in-process index."""
        t = self._t(tenant)
        try:
            idx = t["ids"].index(eid)
            t["ids"].pop(idx)
            t["queries"].pop(idx)
            t["answers"].pop(idx)
            if t["mat"] is not None:
                t["mat"] = np.delete(t["mat"], idx, axis=0)
                if t["mat"].size == 0:
                    t["mat"] = None
        except ValueError:
            pass  # not in index

    # ------------------------------------------------------------------ #
    # Nearest neighbor search
    # ------------------------------------------------------------------ #
    def _nearest_inproc(self, qvec: np.ndarray, tenant: str):
        t = self._t(tenant)
        if t["mat"] is None:
            return None, -1.0, 0.0
        sims = t["mat"] @ qvec.astype(np.float32)
        idx = int(np.argmax(sims))
        best_sim = float(sims[idx])
        within = int(np.count_nonzero((sims < best_sim) & (best_sim - sims <= 0.1)))
        density = min(1.0, within / len(sims))
        return {"query": t["queries"][idx], "answer": t["answers"][idx]}, best_sim, density

    async def _nearest_redisearch(self, qvec: np.ndarray, tenant: str):
        from . import redisearch_store as rs
        try:
            hits = await rs.knn(qvec, tenant, k=5)
        except Exception:
            return None, -1.0, 0.0
        if not hits:
            return None, -1.0, 0.0
        best_q, best_a, best_sim = hits[0]
        sims = [h[2] for h in hits]
        within = sum(1 for s in sims[1:] if best_sim - s <= 0.1)
        density = min(1.0, within / len(sims))
        return {"query": best_q, "answer": best_a}, float(best_sim), density

    async def _nearest(self, qvec: np.ndarray, tenant: str):
        if settings.vector_backend == "redisearch":
            return await self._nearest_redisearch(qvec, tenant)
        return self._nearest_inproc(qvec, tenant)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def lookup(self, query: str, tenant: str) -> LookupResult:
        if not settings.cache_enabled:
            return LookupResult(status="MISS", reason="cache_disabled")

        if is_volatile(query):                                  # Sub-contribution C
            return LookupResult(status="BYPASS", reason="volatile_query")

        qvec = embed(query)
        best, sim, density = await self._nearest(qvec, tenant)             # tenant-scoped
        if best is None:
            return LookupResult(status="MISS", similarity=None, reason="empty_cache")

        hit, reason, threshold = self._policy.decide(query, best["query"], sim, density)
        if not hit:
            return LookupResult(status="MISS", threshold=threshold, similarity=sim, reason=reason)
        return LookupResult(status="HIT", answer=best["answer"], threshold=threshold,
                            similarity=sim, reason=reason)

    async def store(self, query: str, answer: str, tenant: str) -> None:
        if not settings.cache_enabled or is_volatile(query):
            return
        vec = embed(query)

        if settings.vector_backend == "redisearch":
            from . import redisearch_store as rs
            await rs.ensure_index(len(vec))
            await rs.add(query, answer, vec, tenant)
            return

        r = await get_redis()
        eid = uuid.uuid4().hex
        ekey = self._entry_key(tenant, eid)
        now = time.time()
        await r.hset(ekey, mapping={
            "query": query, "answer": answer, "vec": self._vec_to_str(vec), "ts": str(now),
        })
        if settings.cache_ttl_sec > 0:               # optional TTL: bounds memory + self-heals staleness
            await r.expire(ekey, settings.cache_ttl_sec)
        await r.sadd(self._ids_key(tenant), eid)
        # LRU tracking for eviction
        await r.zadd(self._lru_key(tenant), {eid: now})

        # LRU eviction if over limit
        max_entries = settings.max_cache_entries_per_tenant
        if max_entries > 0:
            count = await r.zcard(self._lru_key(tenant))
            if count > max_entries:
                # Remove oldest entries
                to_remove = count - max_entries
                oldest = await r.zpopmin(self._lru_key(tenant), to_remove)
                for old_eid, _ in oldest:
                    await r.delete(self._entry_key(tenant, old_eid))
                    await r.srem(self._ids_key(tenant), old_eid)
                    self._evict_from_index(tenant, old_eid)

        if self._t(tenant)["built"]:
            self._append(tenant, eid, query, answer, vec)

    async def clear(self, tenant: str | None = None) -> None:
        """Clear one tenant's cache, or ALL tenants when tenant is None."""
        r = await get_redis()
        tenants = [tenant] if tenant is not None else list(await self._all_tenants(r))
        for t in tenants:
            for eid in list(await r.smembers(self._ids_key(t))):
                await r.delete(self._entry_key(t, eid))
            await r.delete(self._ids_key(t))
            await r.delete(self._lru_key(t))
            self._index.pop(t, None)
        if tenant is None:
            self._index.clear()

    async def reload(self, tenant: str) -> None:
        """Force a rebuild of a tenant's in-process index from Redis."""
        self._t(tenant).update(built=False, mat=None)
        await self._build_index(tenant)

    async def _all_tenants(self, r) -> list[str]:
        """Tenants known from Redis keys + the in-process index."""
        seen = set(self._index.keys())
        try:
            async for k in r.scan_iter(match="cache:ids:*"):
                seen.add(k.split("cache:ids:", 1)[1])
        except Exception:
            pass
        return list(seen)


# Global instance for backward compatibility (will be replaced by app.state in main.py)
semantic_cache = SemanticCache()