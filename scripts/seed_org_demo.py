"""Reset only the named mock organization workspace and seed a labelled fact.

This is a development fixture, not a quality label or provider generation test.
Run inside the configured gateway container; it makes no provider calls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.cache.semantic_cache import SemanticCache
from app.config import get_settings
from app.embeddings import Embedder
from app.organization import OrganizationDirectory
from app.providers.registry import ProviderRegistry
from app.redis_client import close_redis, create_redis

DEMO_KEY = "example-alice-key-12345"
WORKSPACE = "engineering"
QUESTION = "How do Python decorators work?"
ANSWER = "A Python decorator wraps a function to add behavior without changing its source."


async def seed() -> None:
    config = get_settings()
    if not (
        config.environment == "development"
        and config.llm_provider == "mock"
        and not config.api_key_set
        and config.cache_match_mode == "semantic"
        and config.vector_backend == "redisearch"
        and config.embedding_backend == "minilm"
        and config.answer_policy_artifact
        and Path(config.organization_config_path).name == "organizations-demo.json"
    ):
        raise RuntimeError("Organization fixture requires the explicit local mock demo")
    directory = OrganizationDirectory(config)
    principal = directory.resolve(DEMO_KEY)
    if principal is None or principal.organization_id != "example":
        raise RuntimeError("Designated demo identity unavailable")
    scope, workspace = directory.effective_scope(principal, "workspace", WORKSPACE, QUESTION)
    if scope != "workspace" or workspace != WORKSPACE:
        raise RuntimeError("Designated workspace is not authorized")
    r = create_redis()
    registry = ProviderRegistry.from_profile(
        directory.profiles[principal.provider_profile], directory, r
    )
    try:
        tenant = directory.scoped_tenant(
            principal, scope, workspace, registry.intended_route(QUESTION)
        )
        cache = SemanticCache(r, Embedder())
        await cache.clear(tenant)
        if not await cache.store(QUESTION, ANSWER, tenant):
            raise RuntimeError("Fixture write failed")
        print(f"SEEDED FACTUAL FIXTURE: {QUESTION} => {ANSWER}")
    finally:
        await registry.aclose()
        await close_redis(r)


if __name__ == "__main__":
    asyncio.run(seed())
