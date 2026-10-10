"""Shared test fixtures. Tests run against in-memory fakeredis — no server needed."""

from __future__ import annotations

import os

os.environ.setdefault("REDIS_URL", "")  # force fakeredis
os.environ.setdefault("RATE_LIMIT_CAPACITY", "5")
os.environ.setdefault("RATE_LIMIT_REFILL_PER_SEC", "1")
os.environ.setdefault("EMBEDDING_BACKEND", "hash")  # fast + deterministic for tests
os.environ.setdefault("VERIFIER_NLI", "false")  # no NLI model download in tests
os.environ.setdefault("LLM_PROVIDER", "mock")  # never call a real LLM in tests
os.environ.setdefault("VECTOR_BACKEND", "inproc")  # no external Redis in tests
os.environ.setdefault("API_KEYS", "demo-key-123,tenant-b-key")  # two tenants for isolation test
os.environ.setdefault("METRICS_TOKEN", "test-metrics-token")
os.environ.setdefault("CACHE_SIMILARITY_BASE", "0.5")  # lower threshold for hash embedder

import pytest
from fastapi.testclient import TestClient

from app.cache import redisearch_store as rs
from app.config import settings
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def _set_test_metrics_token():
    """Ensure the test metrics token is set for all tests."""
    pass


@pytest.fixture()
def client(request):
    overrides = getattr(request.node.function, "config_overrides", {})
    app = create_app(settings.model_copy(update=overrides))
    # Use TestClient with lifespan to properly initialize app.state
    # Note: TestClient automatically handles lifespan events
    if os.environ.get("REDIS_URL") and os.environ.get("TEST_ALLOW_REDIS_FLUSHDB") != "1":
        raise RuntimeError(
            "Real Redis tests require explicit TEST_ALLOW_REDIS_FLUSHDB=1 on a disposable database"
        )
    with TestClient(app, raise_server_exceptions=True) as client:
        # Clean slate before each test.
        client.portal.call(_async_reset, client)
        yield client


async def _async_reset(client):
    """Async reset of Redis and cache state."""
    r = client.app.state.redis
    # Tests use a dedicated Redis database in CI; never flush unrelated databases.
    await r.flushdb()
    # Clear the semantic cache in app.state
    if hasattr(client.app.state, "semantic_cache"):
        await client.app.state.semantic_cache.clear()
    if settings.vector_backend == "redisearch":
        await rs.ensure_index(len(client.app.state.model.embed("probe")))


HEADERS = {"x-api-key": "demo-key-123"}
METRICS_HEADERS = {"x-metrics-token": "test-metrics-token"}
