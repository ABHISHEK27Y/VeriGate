"""Isolated sequential/pipelined Redis shortlist-read microbenchmark.

Measures only validation round trips, not HTTP, embedding, or model inference.
Every key is owned by this invocation and deleted in finally.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from pathlib import Path

import redis.asyncio as redis

ROUNDS = 80
SHORTLIST = 5


async def run(output: Path, url: str) -> None:
    if output.exists():
        raise FileExistsError(output)
    client = redis.from_url(url, decode_responses=False)
    prefix = "verigate:shortlist-bench:" + uuid.uuid4().hex
    keys = [f"{prefix}:{i}" for i in range(SHORTLIST)]
    results: dict[str, list[float]] = {"sequential": [], "pipelined": []}
    try:
        for key in keys:
            await client.hset(key, mapping={"tenant": prefix, "query": key, "answer": "x" * 200})
        for index in range(ROUNDS):
            for mode in ("sequential", "pipelined") if index % 2 else ("pipelined", "sequential"):
                started = time.perf_counter()
                if mode == "sequential":
                    rows = [await client.hgetall(key) for key in keys]
                else:
                    async with client.pipeline(transaction=False) as pipe:
                        for key in keys:
                            pipe.hgetall(key)
                        rows = await pipe.execute()
                elapsed = (time.perf_counter() - started) * 1000
                if len(rows) != SHORTLIST or any(not row for row in rows):
                    raise RuntimeError("Shortlist read returned missing data")
                results[mode].append(elapsed)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schema": "redis-shortlist-read-benchmark-v1",
                    "redis_url": url,
                    "rounds": ROUNDS,
                    "shortlist": SHORTLIST,
                    "order": "AB/BA alternating each round",
                    "measurements_ms": results,
                    "median_ms": {
                        mode: statistics.median(values) for mode, values in results.items()
                    },
                    "scope": "Redis hash validation only; not an HTTP latency claim",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    finally:
        await client.delete(*keys)
        await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.output, os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0")))
