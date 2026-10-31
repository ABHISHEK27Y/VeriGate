"""Chronological retrieval replay using the gateway's actual candidate selector.

The caller supplies recorded provider answers for MISS/BYPASS rows. This is a
retrieval replay, not a simulation of provider quality, HTTP, or admission.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.cache.semantic_cache import LookupResult, SemanticCache
from app.config import Settings, _runtime


@dataclass(frozen=True)
class ReplayRow:
    query: str
    generated_answer: str | None = None


async def replay_rows(
    cache: SemanticCache, tenant: str, rows: list[ReplayRow], config: Settings
) -> list[LookupResult]:
    token = _runtime.set(config)
    try:
        decisions = []
        for row in rows:
            decision = await cache.lookup(row.query, tenant)
            decisions.append(decision)
            if decision.status == "MISS" and row.generated_answer is not None:
                await cache.store(row.query, row.generated_answer, tenant)
        return decisions
    finally:
        _runtime.reset(token)
