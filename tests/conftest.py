"""Shared test fixtures. Tests run against in-memory fakeredis — no server needed."""

from __future__ import annotations

import asyncio
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

from app.main import app
from app.redis_client import close_redis, get_redis


@pytest.fixture(scope="session", autouse=True)
def _set_test_metrics_token():
    """Ensure the test metrics token is set for all tests."""
    pass


@pytest.fixture()
def client():
    # Use TestClient with lifespan to properly initialize app.state
    # Note: TestClient automatically handles lifespan events
    with TestClient(app, raise_server_exceptions=True) as client:
        # Clean slate before each test.
        asyncio.run(_async_reset(client))
        yield client


async def _async_reset(client):
    """Async reset of Redis and cache state."""
    r = await get_redis()
    await r.flushall()
    # Clear the semantic cache in app.state
    if hasattr(client.app.state, "semantic_cache"):
        await client.app.state.semantic_cache.clear()
    await close_redis()


HEADERS = {"x-api-key": "demo-key-123"}
METRICS_HEADERS = {"x-metrics-token": "test-metrics-token"}
