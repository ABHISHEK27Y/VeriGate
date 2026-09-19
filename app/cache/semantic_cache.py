"""The semantic cache: vector lookup + the three sub-contributions, PARTITIONED PER TENANT.

Every read and write is scoped to a `tenant` (derived from the caller's API key), so one
tenant's queries can never match another tenant's cached answers. This closes the most
serious risk of a shared semantic cache — cross-tenant data leakage (see docs/SECURITY.md #1).

Storage (Redis is the source of truth):
  cache:ids:<tenant>            -> SET of entry ids for that tenant
  cache:entry:<tenant>:<id>     -> HASH {query, answer, vec(csv), ts}

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

# The live gateway's policy: full VeriGate (adaptive threshold + Tier-1 + optional Tier-2).
_default_policy = CachePolicy(
    static_threshold=settings.cache_similarity_base,
    use_nli=settings.verifier_nli,
)

# in-process vectorised index, keyed by tenant: tenant -> {ids, queries, answers, mat, built}
_INDEX: dict[str, dict] = {}


@dataclass
class LookupResult:
    status: str            # HIT | MISS | BYPASS
    answer: str | None = None
    threshold: float | None = None
    similarity: float | None = None
    reason: str | None = None


def _ids_key(tenant: str) -> str:
    return f"cache:ids:{tenant}"


def _entry_key(tenant: str, eid: str) -> str:
    return f"cache:entry:{tenant}:{eid}"


def _vec_to_str(v: np.ndarray) -> str:
    return ",".join(f"{x:.6f}" for x in v.tolist())


def _str_to_vec(s: str) -> np.ndarray:
    return np.array([float(x) for x in s.split(",") if x], dtype=np.float32)


def _t(tenant: str) -> dict:
    return _INDEX.setdefault(
        tenant, {"ids": [], "queries": [], "answers": [], "mat": None, "built": False}
    )


def _build_index(tenant: str) -> None:
    t = _t(tenant)
    t["ids"].clear(); t["queries"].clear(); t["answers"].clear()
    r = get_redis()
    rows = []
    for eid in r.smembers(_ids_key(tenant)):
        d = r.hgetall(_entry_key(tenant, eid))
        if not d:
            r.srem(_ids_key(tenant), eid)   # entry expired (TTL): drop the dangling id
            continue
        t["ids"].append(eid)
        t["queries"].append(d["query"])
        t["answers"].append(d["answer"])
        rows.append(_str_to_vec(d["vec"]))
    t["mat"] = np.vstack(rows).astype(np.float32) if rows else None
    t["built"] = True


def _ensure(tenant: str) -> None:
    if not _t(tenant)["built"]:
        _build_index(tenant)


def reload(tenant: str) -> None:
    """Force a rebuild of a tenant's in-process index from Redis."""
    _t(tenant).update(built=False, mat=None)
    _build_index(tenant)


def _append(tenant: str, eid: str, query: str, answer: str, vec: np.ndarray) -> None:
    t = _t(tenant)
    t["ids"].append(eid); t["queries"].append(query); t["answers"].append(answer)
    row = vec.astype(np.float32)[None, :]
    t["mat"] = row if t["mat"] is None else np.vstack([t["mat"], row])


def _nearest_inproc(qvec: np.ndarray, tenant: str):
    _ensure(tenant)
    t = _t(tenant)
    if t["mat"] is None:
        return None, -1.0, 0.0
    sims = t["mat"] @ qvec.astype(np.float32)
    idx = int(np.argmax(sims))
    best_sim = float(sims[idx])
    within = int(np.count_nonzero((sims < best_sim) & (best_sim - sims <= 0.1)))
    density = min(1.0, within / len(sims))
    return {"query": t["queries"][idx], "answer": t["answers"][idx]}, best_sim, density


def _nearest_redisearch(qvec: np.ndarray, tenant: str):
    from . import redisearch_store as rs
    try:
        hits = rs.knn(qvec, tenant, k=5)
    except Exception:
        return None, -1.0, 0.0
    if not hits:
        return None, -1.0, 0.0
    best_q, best_a, best_sim = hits[0]
    sims = [h[2] for h in hits]
    within = sum(1 for s in sims[1:] if best_sim - s <= 0.1)
    density = min(1.0, within / len(sims))
    return {"query": best_q, "answer": best_a}, float(best_sim), density


def _nearest(qvec: np.ndarray, tenant: str):
    if settings.vector_backend == "redisearch":
        return _nearest_redisearch(qvec, tenant)
    return _nearest_inproc(qvec, tenant)


def lookup(query: str, tenant: str) -> LookupResult:
    if not settings.cache_enabled:
        return LookupResult(status="MISS", reason="cache_disabled")

    if is_volatile(query):                                  # Sub-contribution C
        return LookupResult(status="BYPASS", reason="volatile_query")

    qvec = embed(query)
    best, sim, density = _nearest(qvec, tenant)             # tenant-scoped
    if best is None:
        return LookupResult(status="MISS", similarity=None, reason="empty_cache")

    hit, reason, threshold = _default_policy.decide(query, best["query"], sim, density)
    if not hit:
        return LookupResult(status="MISS", threshold=threshold, similarity=sim, reason=reason)
    return LookupResult(status="HIT", answer=best["answer"], threshold=threshold,
                        similarity=sim, reason=reason)


def store(query: str, answer: str, tenant: str) -> None:
    if not settings.cache_enabled or is_volatile(query):
        return
    vec = embed(query)

    if settings.vector_backend == "redisearch":
        from . import redisearch_store as rs
        rs.ensure_index(len(vec))
        rs.add(query, answer, vec, tenant)
        return

    r = get_redis()
    eid = uuid.uuid4().hex
    ekey = _entry_key(tenant, eid)
    r.hset(ekey, mapping={
        "query": query, "answer": answer, "vec": _vec_to_str(vec), "ts": str(time.time()),
    })
    if settings.cache_ttl_sec > 0:               # optional TTL: bounds memory + self-heals staleness
        r.expire(ekey, settings.cache_ttl_sec)
    r.sadd(_ids_key(tenant), eid)
    if _t(tenant)["built"]:
        _append(tenant, eid, query, answer, vec)


def clear(tenant: str | None = None) -> None:
    """Clear one tenant's cache, or ALL tenants when tenant is None."""
    r = get_redis()
    tenants = [tenant] if tenant is not None else list(_all_tenants(r))
    for t in tenants:
        for eid in list(r.smembers(_ids_key(t))):
            r.delete(_entry_key(t, eid))
        r.delete(_ids_key(t))
        _INDEX.pop(t, None)
    if tenant is None:
        _INDEX.clear()


def _all_tenants(r):
    """Tenants known from Redis keys + the in-process index."""
    seen = set(_INDEX.keys())
    try:
        for k in r.scan_iter(match="cache:ids:*"):
            seen.add(k.split("cache:ids:", 1)[1])
    except Exception:
        pass
    return seen
