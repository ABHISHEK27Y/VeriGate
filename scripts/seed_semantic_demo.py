"""Seed three factual answers for a disposable, mock-backed semantic demo.

These fixtures demonstrate cache decisions. They are not answer-quality labels or
evidence that the policy is safe on unseen questions. The script clears only the
specified demo API key's tenant and never calls an LLM provider.
"""

from __future__ import annotations

import argparse
import asyncio

from app.cache import redisearch_store as rs
from app.cache.demo_fixtures import DEMO_API_KEY, FACTS, demo_enabled
from app.cache.semantic_cache import SemanticCache
from app.config import get_settings
from app.embeddings import Embedder
from app.identity import tenant_id
from app.redis_client import close_redis, create_redis


async def seed(api_key: str) -> None:
    config = get_settings()
    if not demo_enabled(config):
        raise RuntimeError(
            "Demo seeding requires local mock, Redis Stack, MiniLM and answer policy"
        )
    if api_key != DEMO_API_KEY:
        raise ValueError("Only the designated demo tenant can be reset")
    redis = create_redis()
    binary = create_redis(binary=True)
    token = rs.active_client.set(binary)
    try:
        cache = SemanticCache(redis, Embedder())
        tenant = tenant_id(api_key)
        await cache.clear(tenant)
        for question, answer in FACTS:
            await cache.store(question, answer, tenant)
            print(f"FACTUAL DEMO FIXTURE: {question} => {answer}")
    finally:
        rs.active_client.reset(token)
        await close_redis(redis)
        await close_redis(binary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=DEMO_API_KEY)
    parser.add_argument(
        "--reset-demo-tenant", action="store_true", help="required to clear this demo tenant"
    )
    args = parser.parse_args()
    if not args.reset_demo_tenant:
        parser.error("--reset-demo-tenant is required")
    asyncio.run(seed(args.api_key))
