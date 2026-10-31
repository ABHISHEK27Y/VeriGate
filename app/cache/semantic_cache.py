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
import math
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..config import RuntimeSettings, get_settings
from ..embeddings import Embedder
from ..metrics import STAGE_LATENCY
from ..redis_client import create_redis, hash_fields, remove_member, set_members
from . import redisearch_store as rs
from . import storage
from .answer_policy import AnswerPolicy
from .namespace import namespace
from .policy import CachePolicy
from .verifier import NliVerifier, verifier_scope
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
    cached_query: str | None = None  # needed to audit answer reuse on a HIT
    nli_score: float | None = None
    verifier_invoked: bool = False
    candidate_count: int = 0
    selected_rank: int | None = None
    stage_latency_ms: dict[str, float] = field(default_factory=dict)


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
            use_adaptive=not get_settings().cache_policy_static,
            use_verifier=not get_settings().cache_policy_static,
            static_threshold=get_settings().cache_similarity_base,
            use_nli=get_settings().verifier_nli,
            verifier=NliVerifier(),
        )
        artifact = get_settings().answer_policy_artifact
        policy_bytes = Path(artifact).read_bytes() if artifact else None
        self._answer_policy = AnswerPolicy.load_bytes(policy_bytes) if policy_bytes else None
        runtime = get_settings()
        if isinstance(runtime, RuntimeSettings) and policy_bytes is not None:
            runtime._answer_policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()
        if self._answer_policy and (
            self._answer_policy.model != get_settings().nli_model
            or self._answer_policy.revision != get_settings().nli_revision
        ):
            raise ValueError("Answer policy artifact and runtime NLI model differ")

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
            hits = await rs.knn(qvec, tenant, k=5, include_key=True)
        except Exception:
            logging.getLogger(__name__).exception("RediSearch lookup failed")
            raise
        if not hits:
            return None, -1.0, 0.0
        best_q, best_a, best_sim, best_key = hits[0]
        sims = [h[2] for h in hits]
        within = sum(1 for s in sims[1:] if best_sim - s <= _SIMILARITY_DENSITY_WINDOW)
        density = min(1.0, within / len(sims))
        return {"query": best_q, "answer": best_a, "key": best_key}, float(best_sim), density

    async def _nearest(self, qvec: np.ndarray, tenant: str):
        if get_settings().vector_backend == "redisearch":
            return await self._nearest_redisearch(qvec, tenant)
        return self._nearest_inproc(qvec, tenant)

    async def _ranked(
        self, qvec: np.ndarray, tenant: str, *, refilled: bool = False
    ) -> tuple[list[tuple[dict, float]], float]:
        """Retrieve a stable, scope-filtered shortlist using one request embedding."""
        k = get_settings().semantic_retrieval_k
        if get_settings().vector_backend == "redisearch":
            hits = await rs.knn(qvec, tenant, k=k, include_key=True)
            candidates = [
                ({"query": query, "answer": answer, "key": key}, float(sim))
                for query, answer, sim, key in hits
            ]
        else:
            t = self._t(tenant)
            if t["mat"] is None:
                return [], 0.0
            scores = t["mat"] @ qvec.astype(np.float32)
            ranked = sorted(
                range(len(scores)),
                key=lambda index: (
                    -float(scores[index]) if math.isfinite(float(scores[index])) else math.inf,
                    t["queries"][index],
                    t["ids"][index],
                ),
            )[:k]
            if not refilled and ranked:
                async with self.redis.pipeline(transaction=False) as pipe:
                    for index in ranked:
                        pipe.exists(self._entry_key(tenant, t["ids"][index]))
                    live = await pipe.execute()
                if not all(live):
                    # Natural expiry need not change the Redis version marker.
                    # Rebuild from live hashes once so stale top-k slots refill.
                    await self._build_index(tenant)
                    return await self._ranked(qvec, tenant, refilled=True)
            candidates = [
                (
                    {
                        "id": t["ids"][index],
                        "query": t["queries"][index],
                        "answer": t["answers"][index],
                    },
                    float(scores[index]),
                )
                for index in ranked
            ]
        candidates.sort(
            key=lambda item: (
                -item[1] if math.isfinite(item[1]) else math.inf,
                item[0]["query"],
                item[0].get("id", item[0].get("key", "")),
            )
        )
        if not candidates:
            return [], 0.0
        best = candidates[0][1]
        density = sum(
            math.isfinite(sim) and best - sim <= _SIMILARITY_DENSITY_WINDOW
            for _, sim in candidates[1:]
        ) / len(candidates)
        return candidates, min(1.0, density)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def lookup(self, query: str, tenant: str) -> LookupResult:
        token = verifier_scope.set(tenant)
        try:
            async with self._locks[hash(tenant) % len(self._locks)]:
                return await self._lookup(query, tenant)
        finally:
            verifier_scope.reset(token)

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

    async def _lookup(self, query: str, tenant: str) -> LookupResult:  # noqa: PLR0911, PLR0912, PLR0915
        stage_ms: dict[str, float] = {}
        if not get_settings().cache_enabled:
            return LookupResult(status="MISS", reason="cache_disabled")

        if is_volatile(query):  # Sub-contribution C
            return LookupResult(status="BYPASS", reason="volatile_query")

        if get_settings().cache_match_mode == "exact":
            eid = hashlib.sha256(query.encode("utf-8")).hexdigest()
            stage_started = time.perf_counter()
            row = await hash_fields(self.redis, self._entry_key(tenant, eid))
            elapsed = time.perf_counter() - stage_started
            STAGE_LATENCY.labels(stage="exact_lookup").observe(elapsed)
            stage_ms["exact_lookup"] = round(elapsed * 1000, 3)
            if row and row.get("query") == query:
                await storage.touch(self.redis, tenant, eid)
                return LookupResult(
                    status="HIT",
                    answer=row["answer"],
                    reason="exact_match",
                    cached_query=row["query"],
                    stage_latency_ms=stage_ms,
                )
            return LookupResult(
                status="MISS", reason="exact_match_required", stage_latency_ms=stage_ms
            )

        # Semantic mode still serves an identical question without embedding or NLI.
        # The deterministic ID is scope-local; reread after touching so a concurrent
        # replacement or expiry cannot serve an earlier generation of the entry.
        eid = hashlib.sha256(query.encode("utf-8")).hexdigest()
        exact_started = time.perf_counter()
        current: dict[str, str] | None
        if get_settings().vector_backend == "redisearch":
            key = f"{rs._namespace()}:entry:{tenant}:{eid}"
            semantic_row = await rs.read_candidate(key, tenant)
            if semantic_row and semantic_row["query"] == query:
                await rs.touch_candidate(key, tenant)
                current = await rs.read_candidate(key, tenant)
            else:
                current = None
        else:
            key = self._entry_key(tenant, eid)
            semantic_row = await hash_fields(self.redis, key)
            if semantic_row and semantic_row.get("query") == query:
                await storage.touch(self.redis, tenant, eid)
                current = await hash_fields(self.redis, key)
            else:
                current = None
        elapsed = time.perf_counter() - exact_started
        STAGE_LATENCY.labels(stage="exact_lookup").observe(elapsed)
        stage_ms["exact_lookup"] = round(elapsed * 1000, 3)
        if current and current.get("query") == query:
            return LookupResult(
                status="HIT",
                answer=current["answer"],
                similarity=1.0,
                reason="exact_match",
                cached_query=query,
                candidate_count=1,
                selected_rank=1,
                stage_latency_ms=stage_ms,
            )
        if semantic_row and semantic_row.get("query") == query:
            return LookupResult(
                status="MISS", reason="exact_candidate_changed", stage_latency_ms=stage_ms
            )

        # Ensure index is built from Redis before searching
        if get_settings().vector_backend != "redisearch":
            # Redis is authoritative, including writes/clears made by other workers.
            stage_started = time.perf_counter()
            await self._ensure(tenant)
            elapsed = time.perf_counter() - stage_started
            STAGE_LATENCY.labels(stage="index_sync").observe(elapsed)
            stage_ms["index_sync"] = round(elapsed * 1000, 3)

        stage_started = time.perf_counter()
        qvec = await self._infer(self.embedder.embed, query)
        elapsed = time.perf_counter() - stage_started
        STAGE_LATENCY.labels(stage="embedding").observe(elapsed)
        stage_ms["embedding"] = round(elapsed * 1000, 3)
        stage_started = time.perf_counter()
        candidates, density = await self._ranked(qvec, tenant)  # tenant-scoped
        elapsed = time.perf_counter() - stage_started
        STAGE_LATENCY.labels(stage="retrieval").observe(elapsed)
        stage_ms["retrieval"] = round(elapsed * 1000, 3)
        if not candidates:
            return LookupResult(
                status="MISS", similarity=None, reason="empty_cache", stage_latency_ms=stage_ms
            )
        count = len(candidates)
        exact = [
            (rank, candidate, sim)
            for rank, (candidate, sim) in enumerate(candidates, 1)
            if candidate["query"] == query
        ]
        if exact:
            if len({candidate["answer"] for _, candidate, _ in exact}) != 1:
                return LookupResult(
                    status="MISS",
                    reason="conflicting_exact_entries",
                    candidate_count=count,
                    stage_latency_ms=stage_ms,
                )
            rank, best, sim = exact[0]
            reason, threshold, nli_score, verifier_invoked = "exact_match", None, None, False
        else:
            best, sim = candidates[0]
            rank = 1
            threshold, nli_score, verifier_invoked = None, None, False
            reason = "no_acceptable_candidate"
        stage_started = time.perf_counter()
        hit = bool(exact)
        if not exact and self._answer_policy is not None:
            threshold = self._answer_policy.min_similarity
            accepted = []
            deadline = time.perf_counter() + get_settings().semantic_verify_budget_ms / 1000
            limit = min(count, get_settings().semantic_verify_limit)
            for candidate_rank, (candidate, score) in enumerate(candidates[:limit], 1):
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    reason = "verification_budget_exhausted"
                    break
                try:
                    decision = await asyncio.wait_for(
                        self._infer(
                            self._answer_policy.decide,
                            query,
                            candidate["query"],
                            candidate["answer"],
                            score,
                            self._policy.verifier,
                            get_settings().answer_policy_subject_guard,
                            get_settings().answer_policy_technical_guard,
                        ),
                        timeout=remaining,
                    )
                except TimeoutError:
                    reason = "verification_budget_exhausted"
                    break
                decision_reason = f"answer_{decision.action.lower()}:{decision.reason}"
                if candidate_rank == 1:
                    reason = decision_reason
                    nli_score = decision.score
                verifier_invoked |= decision.score is not None or decision.reason in {
                    "verifier_unavailable",
                    "context_too_long",
                }
                if decision.action == "ACCEPT":
                    accepted.append(
                        (candidate_rank, candidate, score, decision.score, decision_reason)
                    )
            else:
                if count > limit and candidates[limit][1] >= threshold:
                    reason = "verification_limit_exhausted"
                elif len({item[1]["answer"].strip().casefold() for item in accepted}) > 1:
                    reason = "conflicting_accepted_answers"
                elif accepted:
                    rank, best, sim, nli_score, reason = accepted[0]
                    hit = True
        elif not exact:
            hit, reason, threshold = await self._infer(
                self._policy.decide, query, best["query"], sim, density
            )
            verifier_invoked = get_settings().verifier_nli and "nli" in reason
        elapsed = time.perf_counter() - stage_started
        STAGE_LATENCY.labels(stage="policy_decision").observe(elapsed)
        stage_ms["policy_decision"] = round(elapsed * 1000, 3)
        if not hit:
            return LookupResult(
                status="MISS",
                threshold=threshold,
                similarity=sim,
                reason=reason,
                cached_query=best["query"],
                nli_score=nli_score,
                verifier_invoked=verifier_invoked,
                candidate_count=count,
                stage_latency_ms=stage_ms,
            )
        stage_started = time.perf_counter()
        if get_settings().vector_backend == "redisearch":
            candidate_row = await rs.read_candidate(best["key"], tenant)
        else:
            candidate_row = await hash_fields(self.redis, self._entry_key(tenant, best["id"]))
        elapsed = time.perf_counter() - stage_started
        STAGE_LATENCY.labels(stage="candidate_identity").observe(elapsed)
        stage_ms["candidate_identity"] = round(elapsed * 1000, 3)
        if not candidate_row:
            return LookupResult(
                status="MISS",
                reason="expired_or_evicted",
                candidate_count=count,
                stage_latency_ms=stage_ms,
            )
        if (
            candidate_row.get("query") != best["query"]
            or candidate_row.get("answer") != best["answer"]
        ):
            return LookupResult(
                status="MISS",
                reason="candidate_changed",
                candidate_count=count,
                stage_latency_ms=stage_ms,
            )
        if get_settings().vector_backend == "redisearch":
            await rs.touch_candidate(best["key"], tenant)
        else:
            await storage.touch(self.redis, tenant, best["id"])
        return LookupResult(
            status="HIT",
            answer=best["answer"],
            threshold=threshold,
            similarity=sim,
            reason=reason,
            cached_query=best["query"],
            nli_score=nli_score,
            verifier_invoked=verifier_invoked,
            candidate_count=count,
            selected_rank=rank,
            stage_latency_ms=stage_ms,
        )

    async def store(self, query: str, answer: str, tenant: str) -> bool:
        async with self._locks[hash(tenant) % len(self._locks)]:
            return await self._store(query, answer, tenant)

    async def _store(self, query: str, answer: str, tenant: str) -> bool:
        if not answer.strip() or not get_settings().cache_enabled or is_volatile(query):
            return False
        if (
            len(query.encode("utf-8")) + len(answer.encode("utf-8"))
            > get_settings().max_cache_entry_bytes
        ):
            return False
        if get_settings().cache_match_mode == "exact":
            return await storage.put(
                self.redis,
                tenant,
                hashlib.sha256(query.encode("utf-8")).hexdigest(),
                {"query": query, "answer": answer, "vec": ""},
            )
        vec = await self._infer(self.embedder.embed, query)

        if get_settings().vector_backend == "redisearch":
            await rs.ensure_index(len(vec))
            return bool(await rs.add(query, answer, vec, tenant))

        eid = hashlib.sha256(query.encode("utf-8")).hexdigest()
        stored = await storage.put(
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
        if stored:
            self._index.pop(tenant, None)
            self._versions.pop(tenant, None)
        return stored

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
