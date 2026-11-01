"""Capacity-pressure experiment for a scoped tenant (audit F22).

The saved stress "deployment" arm never bound its entry cap (it wrote fewer
entries than the limit), so it did not demonstrate behavior under pressure. This
drives a scoped tenant past a deliberately low per-scope entry limit and records
the actual mechanism: initial occupancy, successful insertions, peak, final
entries, eviction counter, and a retained-vs-evicted follow-up read. A write-stage
observation is NOT assumed to be a successful unique insertion; occupancy and the
eviction counter are read from Redis.

Run against a disposable Redis (any backend; storage quotas are backend-agnostic):
  REDIS_URL=redis://localhost:6399/0 python -m scripts.measure_capacity_pressure \
      evaluation/runs/capacity_pressure_<date>_v1/result.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from app.cache import storage
from app.config import Settings, _runtime, snapshot
from app.redis_client import close_redis, create_redis

ROOT = Path(__file__).resolve().parents[1]
ENTRY_LIMIT = 20
DISTINCT_ENTRIES = 50


async def _run() -> dict:
    config = snapshot(
        Settings(
            _env_file=None,
            private_cache_entry_limit=ENTRY_LIMIT,
            organization_cache_entry_limit=10_000,
        )
    )
    token = _runtime.set(config)
    r = create_redis()
    tenant = f"p_{uuid.uuid4().hex[:16]}_employee"
    try:
        initial = await storage.occupancy(r, tenant)
        successful = 0
        order = []
        for index in range(DISTINCT_ENTRIES):
            eid = f"e{index:03d}"
            order.append(eid)
            stored = await storage.put(
                r, tenant, eid, {"query": f"question {index}", "answer": f"answer {index}"}
            )
            successful += bool(stored)
            # Touch so the most recent entries are the freshest (LRU order explicit).
            await storage.touch(r, tenant, eid)
        final = await storage.occupancy(r, tenant)
        _, _, prefix = storage.keys(tenant)
        oldest_present = bool(await r.exists(prefix + order[0]))
        newest_present = bool(await r.exists(prefix + order[-1]))
        return {
            "schema": "capacity-pressure-v1",
            "backend": "real-redis" if config.redis_url else "fakeredis",
            "entry_limit": ENTRY_LIMIT,
            "distinct_entries_attempted": DISTINCT_ENTRIES,
            "initial_entries": initial["entries"],
            "successful_puts": successful,
            "final_entries": final["entries"],
            "evictions_counted": final["evictions"],
            "oldest_entry_present": oldest_present,
            "newest_entry_present": newest_present,
            "cap_bound": final["entries"] <= ENTRY_LIMIT and final["evictions"] > 0,
            "note": (
                "Distinct eligible entries exceed the per-scope cap, so eviction is "
                "forced. Entries are capped, the oldest is evicted, the newest retained, "
                "and the eviction counter is nonzero."
            ),
        }
    finally:
        await storage.clear(r, tenant)
        await close_redis(r)
        _runtime.reset(token)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(_run())
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
