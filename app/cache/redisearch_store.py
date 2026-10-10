"""Binary-safe RediSearch storage with bounded connections and atomic cache metadata."""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

import numpy as np
import redis.asyncio as redis
from redis.exceptions import ResponseError

from ..config import get_settings
from ..embeddings import embed
from . import storage
from .namespace import namespace

log = logging.getLogger(__name__)
active_client: ContextVar[redis.Redis | None] = ContextVar("redisearch_client", default=None)


def _index() -> str:
    return namespace().replace(":", "_") + "_idx"


def _namespace() -> str:
    return namespace() + ":rs"


@asynccontextmanager
async def _client():
    existing = active_client.get()
    if existing is not None:
        yield existing
        return
    if not get_settings().redis_url:
        raise RuntimeError("RediSearch requires REDIS_URL")
    r = redis.from_url(
        get_settings().redis_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
        max_connections=20,
    )
    try:
        yield r
    finally:
        await r.aclose()


async def redisearch_available() -> bool:
    try:
        async with _client() as r:
            await r.execute_command("FT._LIST")
    except Exception:
        log.warning("RediSearch availability check failed", exc_info=True)
        return False
    else:
        return True


async def ensure_index(dim: int) -> None:
    async with _client() as r:
        try:
            await r.execute_command(
                "FT.CREATE",
                _index(),
                "ON",
                "HASH",
                "PREFIX",
                1,
                f"{_namespace()}:entry:",
                "SCHEMA",
                "tenant",
                "TAG",
                "query",
                "TEXT",
                "answer",
                "TEXT",
                "vec",
                "VECTOR",
                "HNSW",
                6,
                "TYPE",
                "FLOAT32",
                "DIM",
                dim,
                "DISTANCE_METRIC",
                "COSINE",
            )
        except ResponseError as exc:
            if "index already exists" not in str(exc).lower():
                raise
    await validate_index(dim)


async def validate_index(dim: int) -> None:
    async with _client() as r:
        info = await r.execute_command("FT.INFO", _index())
    fields = dict(zip(info[::2], info[1::2], strict=True))
    for attribute in fields.get(b"attributes", []):
        values = dict(zip(attribute[::2], attribute[1::2], strict=True))
        if values.get(b"attribute") == b"vec":
            if (
                int(values.get(b"dim", 0)) != dim
                or values.get(b"distance_metric") != b"COSINE"
                or values.get(b"data_type") != b"FLOAT32"
            ):
                raise RuntimeError("Incompatible RediSearch vector schema")
            return
    raise RuntimeError("RediSearch vector field missing")


async def add(query: str, answer: str, vec: np.ndarray, tenant: str) -> str:
    eid = uuid.uuid4().hex
    async with _client() as r:
        await storage.put(
            r,
            tenant,
            eid,
            {
                "tenant": tenant,
                "query": query,
                "answer": answer,
                "vec": np.asarray(vec, dtype=np.float32).tobytes(),
            },
            namespace=_namespace(),
        )
    return eid


async def clear(tenant: str | None = None) -> None:
    async with _client() as r:
        if tenant is not None:
            await storage.clear(r, tenant, namespace=_namespace())
        else:
            async for key in r.scan_iter(match=f"{_namespace()}:ids:*"):
                await storage.clear(
                    r, key.decode().split(f"{_namespace()}:ids:", 1)[1], namespace=_namespace()
                )


async def knn(vec: np.ndarray, tenant: str, k: int = 1):
    # Escape TAG syntax even for callers outside the authenticated gateway.
    escaped = re.sub(r"([^a-zA-Z0-9_])", lambda m: "\\" + m[0], tenant)
    q = f"(@tenant:{{{escaped}}})=>[KNN {k} @vec $BLOB AS score]"
    async with _client() as r:
        res = await r.execute_command(
            "FT.SEARCH",
            _index(),
            q,
            "PARAMS",
            2,
            "BLOB",
            np.asarray(vec, dtype=np.float32).tobytes(),
            "SORTBY",
            "score",
            "RETURN",
            3,
            "query",
            "answer",
            "score",
            "LIMIT",
            0,
            k,
            "DIALECT",
            2,
        )
        out = []
        for i in range(1, len(res), 2):
            # Confirm existence after search; a concurrent TTL/clear cannot revive stale answers.
            key = res[i]
            row = await r.hgetall(key)
            if not row:
                continue
            fields = res[i + 1]
            values = dict(zip(fields[::2], fields[1::2], strict=True))
            out.append(
                (
                    row[b"query"].decode(),
                    row[b"answer"].decode(),
                    1.0 - float(values.get(b"score", b"1")),
                )
            )
            eid = key.decode().rsplit(":", 1)[1]
            await r.zadd(f"{_namespace()}:lru:{tenant}", {eid: time.time()}, xx=True)
        return out


async def smoke_test() -> None:
    """Run against a live Redis Stack to validate this backend end-to-end."""

    if not await redisearch_available():
        raise RuntimeError(
            "RediSearch not available. Start Redis Stack and set REDIS_URL. "
            "See docs/REDISEARCH_UPGRADE.md."
        )
    dim = len(embed("dimension probe"))
    await ensure_index(dim)
    await add(
        "how do I reset my password",
        "Go to Settings > Security.",
        embed("how do I reset my password"),
        tenant="t_demo",
    )
    hits = await knn(embed("what is the process to recover my account password"), "t_demo", k=1)
    print("KNN result:", hits)
    assert hits, "expected at least one neighbour"
    # isolation: a different tenant must NOT see t_demo's entry
    other = await knn(embed("how do I reset my password"), "t_other", k=1)
    assert not other, "tenant isolation failed: another tenant saw the entry"
    print("RediSearch smoke test passed (incl. tenant isolation).")


if __name__ == "__main__":
    import asyncio

    asyncio.run(smoke_test())
