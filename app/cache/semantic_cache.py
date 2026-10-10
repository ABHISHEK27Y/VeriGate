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

import asyncio
import hashlib
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from ..config import get_settings
from ..embeddings import Embedder
from ..redis_client import create_redis, hash_fields, remove_member, set_members
from . import redisearch_store as rs
from . import storage
from .namespace import namespace
from .policy import CachePolicy
from .verifier import NliVerifier
from .volatility import is_volatile

# Constants
_SIMILARITY_DENSITY_WINDOW = 0.1  # similarity window for density calculation


@dataclass(slots=True, frozen=True)
class LookupResult:
    status: str  # HIT | MISS | BYPASS
    answer: str | None = None
    threshold: float | None = None
    similarity: float | None = None
    reason: str | None = None


class SemanticCache:
    """Async semantic cache with per-tenant isolation and LRU eviction."""

    def __init__(self, redis_client=None, embedder=None) -> None:
        self.embedder = embedder if embedder is not None else Embedder()
        self.redis = redis_client if redis_client is not None else create_redis()
        # in-process vectorised index, keyed by tenant
        self._index: dict[str, dict] = OrderedDict()
        self._locks = [asyncio.Lock() for _ in range(64)]
        self._inference_gate = asyncio.Semaphore(1)
        self._versions: dict[str, str | None] = {}
        self._policy = CachePolicy(
            static_threshold=get_settings().cache_similarity_base,
            use_nli=get_settings().verifier_nli,
            verifier=NliVerifier(),
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _ids_key(self, tenant: str) -> str:
        return f"{namespace()}:ids:{tenant}"

    def _entry_key(self, tenant: str, eid: str) -> str:
        return f"{namespace()}:entry:{tenant}:{eid}"

    def _lru_key(self, tenant: str) -> str:
        return f"{namespace()}:lru:{tenant}"

    def _vec_to_str(self, v: np.ndarray) -> str:
        return ",".join(f"{x:.6f}" for x in v.tolist())

    def _str_to_vec(self, s: str) -> np.ndarray:
        return np.array([float(x) for x in s.split(",") if x], dtype=np.float32)

    def _t(self, tenant: str) -> dict:
        if tenant not in self._index and len(self._index) >= get_settings().max_cached_tenants:
            oldest = next(iter(self._index))
            self._index.pop(oldest)
            self._versions.pop(oldest, None)
        return self._index.setdefault(
            tenant, {"ids": [], "queries": [], "answers": [], "mat": None, "built": False}
        )

    async def _build_index(self, tenant: str) -> None:
        # Build privately: another coroutine must never observe half-built parallel arrays.
        t: dict = {"ids": [], "queries": [], "answers": [], "mat": None, "built": False}
        r = self.redis
        rows = []
        ids = list(await set_members(r, self._ids_key(tenant)))
        batch_size = 64
        for offset in range(0, len(ids), batch_size):
            batch = ids[offset : offset + batch_size]
            async with r.pipeline(transaction=False) as pipe:
                for eid in batch:
                    pipe.hgetall(self._entry_key(tenant, eid))
                records = await pipe.execute()
            for eid, record in zip(batch, records, strict=True):
                if not record:
                    await remove_member(r, self._ids_key(tenant), eid)
                    await r.zrem(self._lru_key(tenant), eid)
                    continue
                t["ids"].append(eid)
                t["queries"].append(record["query"])
                t["answers"].append(record["answer"])
                rows.append(self._str_to_vec(record["vec"]))
        t["mat"] = np.vstack(rows).astype(np.float32) if rows else None
        t["built"] = True
        self._t(tenant)  # enforce the tenant bound even after concurrent rebuilds
        self._index[tenant] = t

    async def _ensure(self, tenant: str) -> None:
        version = await self.redis.get(f"{namespace()}:version:{tenant}")
        if not self._t(tenant)["built"] or self._versions.get(tenant) != version:
            await self._build_index(tenant)
            self._versions[tenant] = version

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
        within = int(
            np.count_nonzero((sims < best_sim) & (best_sim - sims <= _SIMILARITY_DENSITY_WINDOW))
        )
        density = min(1.0, within / len(sims))
        return (
            {"id": t["ids"][idx], "query": t["queries"][idx], "answer": t["answers"][idx]},
            best_sim,
            density,
        )

    async def _nearest_redisearch(self, qvec: np.ndarray, tenant: str):
        try:
            hits = await rs.knn(qvec, tenant, k=5)
        except Exception:
            logging.getLogger(__name__).exception("RediSearch lookup failed")
            raise
        if not hits:
            return None, -1.0, 0.0
        best_q, best_a, best_sim = hits[0]
        sims = [h[2] for h in hits]
        within = sum(1 for s in sims[1:] if best_sim - s <= _SIMILARITY_DENSITY_WINDOW)
        density = min(1.0, within / len(sims))
        return {"query": best_q, "answer": best_a}, float(best_sim), density

    async def _nearest(self, qvec: np.ndarray, tenant: str):
        if get_settings().vector_backend == "redisearch":
            return await self._nearest_redisearch(qvec, tenant)
        return self._nearest_inproc(qvec, tenant)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def lookup(self, query: str, tenant: str) -> LookupResult:
        async with self._locks[hash(tenant) % len(self._locks)]:
            return await self._lookup(query, tenant)

    async def _infer(self, function, *args):
        # Cancellation must not release capacity while the underlying thread still runs.
        await self._inference_gate.acquire()
        task = asyncio.create_task(asyncio.to_thread(function, *args))

        def finished(completed):
            self._inference_gate.release()
            if not completed.cancelled():
                completed.exception()  # retrieve abandoned exceptions after request cancellation

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _lookup(self, query: str, tenant: str) -> LookupResult:  # noqa: PLR0911
        if not get_settings().cache_enabled:
            return LookupResult(status="MISS", reason="cache_disabled")

        if is_volatile(query):  # Sub-contribution C
            return LookupResult(status="BYPASS", reason="volatile_query")

        if get_settings().cache_match_mode == "exact":
            eid = hashlib.sha256(query.encode("utf-8")).hexdigest()
            row = await hash_fields(self.redis, self._entry_key(tenant, eid))
            if row and row.get("query") == query:
                await self.redis.zadd(self._lru_key(tenant), {eid: time.time()}, xx=True)
                return LookupResult(status="HIT", answer=row["answer"], reason="exact_match")
            return LookupResult(status="MISS", reason="exact_match_required")

        # Ensure index is built from Redis before searching
        if get_settings().vector_backend != "redisearch":
            # Redis is authoritative, including writes/clears made by other workers.
            await self._ensure(tenant)

        qvec = await self._infer(self.embedder.embed, query)
        best, sim, density = await self._nearest(qvec, tenant)  # tenant-scoped
        if best is None:
            return LookupResult(status="MISS", similarity=None, reason="empty_cache")

        hit, reason, threshold = await self._infer(
            self._policy.decide, query, best["query"], sim, density
        )
        if not hit:
            return LookupResult(status="MISS", threshold=threshold, similarity=sim, reason=reason)
        if get_settings().vector_backend != "redisearch":
            row = await hash_fields(self.redis, self._entry_key(tenant, best["id"]))
            if not row:
                return LookupResult(status="MISS", reason="expired_or_evicted")
            best["answer"] = row["answer"]
            await self.redis.zadd(self._lru_key(tenant), {best["id"]: time.time()}, xx=True)
        return LookupResult(
            status="HIT", answer=best["answer"], threshold=threshold, similarity=sim, reason=reason
        )

    async def store(self, query: str, answer: str, tenant: str) -> None:
        async with self._locks[hash(tenant) % len(self._locks)]:
            await self._store(query, answer, tenant)

    async def _store(self, query: str, answer: str, tenant: str) -> None:
        if not get_settings().cache_enabled or is_volatile(query):
            return
        if (
            len(query.encode("utf-8")) + len(answer.encode("utf-8"))
            > get_settings().max_cache_entry_bytes
        ):
            return
        if get_settings().cache_match_mode == "exact":
            await storage.put(
                self.redis,
                tenant,
                hashlib.sha256(query.encode("utf-8")).hexdigest(),
                {"query": query, "answer": answer, "vec": ""},
            )
            return
        vec = await self._infer(self.embedder.embed, query)

        if get_settings().vector_backend == "redisearch":
            await rs.ensure_index(len(vec))
            await rs.add(query, answer, vec, tenant)
            return

        eid = uuid.uuid4().hex
        await storage.put(
            self.redis,
            tenant,
            eid,
            {
                "query": query,
                "answer": answer,
                "vec": self._vec_to_str(vec),
                "ts": str(time.time()),
            },
        )
        self._index.pop(tenant, None)
        self._versions.pop(tenant, None)

    async def clear(self, tenant: str | None = None) -> None:
        if tenant is None:
            for known in await self._all_tenants(self.redis):
                await self.clear(known)
            if get_settings().vector_backend == "redisearch":
                await rs.clear()
            return
        async with self._locks[hash(tenant) % len(self._locks)]:
            await self._clear(tenant)

    async def _clear(self, tenant: str | None = None) -> None:
        """Clear one tenant's cache, or ALL tenants when tenant is None."""
        if (
            get_settings().vector_backend == "redisearch"
            and get_settings().cache_match_mode == "semantic"
        ):
            await rs.clear(tenant)
            return
        r = self.redis
        tenants = [tenant] if tenant is not None else list(await self._all_tenants(r))
        for t in tenants:
            await storage.clear(r, t)
            self._index.pop(t, None)
            self._versions.pop(t, None)
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
            async for k in r.scan_iter(match=f"{namespace()}:ids:*"):  # type: ignore[misc]
                seen.add(k.split(f"{namespace()}:ids:", 1)[1])
        except Exception:
            logging.getLogger(__name__).exception("Cache tenant scan failed")
            raise
        return list(seen)
