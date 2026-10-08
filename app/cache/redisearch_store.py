"""RediSearch vector store — the production, multi-replica form of the KNN index.

The in-process vectorised index in `semantic_cache.py` is exact and sub-millisecond for
thousands of vectors, but each gateway replica keeps its own copy. For horizontal scale and
millions of vectors, the index should live in Redis itself as an ANN (HNSW) index that all
replicas share. That is what this module provides.

REQUIRES **Redis Stack** (RediSearch module) — plain Redis / fakeredis do NOT support
FT.CREATE. This sandbox has no Docker, so this path is provided as a ready-to-run reference
and is validated by `smoke_test()` once you point it at a Redis Stack instance
(see docs/REDISEARCH_UPGRADE.md).

Design notes:
 * Vectors are stored as raw FLOAT32 bytes (not CSV) in the hash field `vec`, so this module
   uses its OWN binary-safe client (decode_responses=False).
 * Cosine distance; similarity = 1 - distance.
"""
from __future__ import annotations

import struct
import uuid

import numpy as np

from ..config import settings

_INDEX = "verigate_idx"
_PREFIX = "cache:entry:"


def _client():
    """A binary-safe Redis client (decode_responses=False) for byte vectors."""
    import redis

    url = settings.redis_url or "redis://localhost:6379/0"
    return redis.Redis.from_url(url, decode_responses=False)


def redisearch_available() -> bool:
    """True only if the server has the RediSearch module (i.e. Redis Stack)."""
    try:
        r = _client()
        modules = r.execute_command("MODULE", "LIST")
        names = [str(m[1], "utf-8").lower() for m in modules] if modules else []
        return any("search" in n for n in names)
    except Exception:
        return False


def ensure_index(dim: int) -> None:
    """Create the HNSW vector index if it does not already exist."""
    r = _client()
    try:
        r.execute_command("FT.INFO", _INDEX)
        return  # already exists
    except Exception:
        pass
    r.execute_command(
        "FT.CREATE", _INDEX, "ON", "HASH", "PREFIX", 1, _PREFIX,
        "SCHEMA",
        "tenant", "TAG",
        "query", "TEXT",
        "answer", "TEXT",
        "vec", "VECTOR", "HNSW", 6,
        "TYPE", "FLOAT32", "DIM", dim, "DISTANCE_METRIC", "COSINE",
    )


def add(query: str, answer: str, vec: np.ndarray, tenant: str) -> str:
    r = _client()
    eid = uuid.uuid4().hex
    r.hset(f"{_PREFIX}{tenant}:{eid}", mapping={
        b"tenant": tenant.encode("utf-8"),
        b"query": query.encode("utf-8"),
        b"answer": answer.encode("utf-8"),
        b"vec": np.asarray(vec, dtype=np.float32).tobytes(),
    })
    return eid


def knn(vec: np.ndarray, tenant: str, k: int = 1):
    """Return [(query, answer, similarity), ...] for the k nearest neighbours of this tenant."""
    r = _client()
    # Pre-filter by tenant TAG, then KNN within that partition (tenant isolation).
    q = (f"(@tenant:{{{tenant}}})=>[KNN {k} @vec $BLOB AS score]")
    res = r.execute_command(
        "FT.SEARCH", _INDEX, q,
        "PARAMS", 2, "BLOB", np.asarray(vec, dtype=np.float32).tobytes(),
        "SORTBY", "score", "RETURN", 3, "query", "answer", "score",
        "DIALECT", 2,
    )
    out = []
    # res = [count, key1, [field, val, field, val, ...], key2, [...], ...]
    for i in range(1, len(res), 2):
        fields = res[i + 1]
        d = {str(fields[j], "utf-8"): fields[j + 1] for j in range(0, len(fields), 2)}
        query = str(d.get("query", b""), "utf-8")
        answer = str(d.get("answer", b""), "utf-8")
        dist = float(d.get("score", b"1"))
        out.append((query, answer, 1.0 - dist))  # cosine distance -> similarity
    return out


def smoke_test() -> None:
    """Run against a live Redis Stack to validate this backend end-to-end."""
    from ..embeddings import embed

    if not redisearch_available():
        raise RuntimeError(
            "RediSearch not available. Start Redis Stack and set REDIS_URL. "
            "See docs/REDISEARCH_UPGRADE.md."
        )
    dim = len(embed("dimension probe"))
    ensure_index(dim)
    add("how do I reset my password", "Go to Settings > Security.",
        embed("how do I reset my password"), tenant="t_demo")
    hits = knn(embed("what is the process to recover my account password"), "t_demo", k=1)
    print("KNN result:", hits)
    assert hits, "expected at least one neighbour"
    # isolation: a different tenant must NOT see t_demo's entry
    other = knn(embed("how do I reset my password"), "t_other", k=1)
    assert not other, "tenant isolation failed: another tenant saw the entry"
    print("RediSearch smoke test passed (incl. tenant isolation).")


if __name__ == "__main__":
    smoke_test()
