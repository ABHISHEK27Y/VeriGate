"""Seed three factual answers for a disposable, mock-backed semantic demo.

These fixtures demonstrate cache decisions. They are not answer-quality labels or
evidence that the policy is safe on unseen questions. The script clears only the
specified demo API key's tenant and never calls an LLM provider.
"""

from __future__ import annotations

import argparse
import asyncio

from app.cache import redisearch_store as rs
from app.cache.semantic_cache import SemanticCache
from app.config import get_settings
from app.embeddings import Embedder
from app.identity import tenant_id
from app.redis_client import close_redis, create_redis

FACTS = (
    ("Who wrote the novel Pride and Prejudice?", "Jane Austen"),
    ("In what year did Apollo 11 land on the Moon?", "1969"),
    ("Which planet is known as the Red Planet?", "Mars"),
)


async def seed(api_key: str) -> None:
    config = get_settings()
    if (
        config.environment == "production"
        or config.llm_provider != "mock"
        or config.cache_match_mode != "semantic"
        or not config.answer_policy_artifact
        or not config.redis_url
        or config.vector_backend != "redisearch"
        or config.embedding_backend != "minilm"
    ):
        raise RuntimeError(
            "Demo seeding requires local mock, Redis Stack, MiniLM and answer policy"
        )
    if api_key not in config.api_key_set:
        raise ValueError("Demo API key is not configured")
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
    parser.add_argument("--api-key", default="demo-key-123")
    parser.add_argument(
        "--reset-demo-tenant", action="store_true", help="required to clear this demo tenant"
    )
    args = parser.parse_args()
    if not args.reset_demo_tenant:
        parser.error("--reset-demo-tenant is required")
    asyncio.run(seed(args.api_key))
