"""Shared test fixtures. Tests run against in-memory fakeredis — no server needed."""
import os

os.environ.setdefault("REDIS_URL", "")            # force fakeredis
os.environ.setdefault("RATE_LIMIT_CAPACITY", "5")
os.environ.setdefault("RATE_LIMIT_REFILL_PER_SEC", "1")
os.environ.setdefault("EMBEDDING_BACKEND", "hash")  # fast + deterministic for tests
os.environ.setdefault("VERIFIER_NLI", "false")       # no NLI model download in tests
os.environ.setdefault("LLM_PROVIDER", "mock")        # never call a real LLM in tests
os.environ.setdefault("VECTOR_BACKEND", "inproc")    # no external Redis in tests
os.environ.setdefault("API_KEYS", "demo-key-123,tenant-b-key")  # two tenants for isolation test

import pytest
from fastapi.testclient import TestClient

from app.cache import semantic_cache
from app.main import app
from app.redis_client import get_redis


@pytest.fixture()
def client():
    # Clean slate before each test.
    get_redis().flushall()
    semantic_cache.clear()
    return TestClient(app)


HEADERS = {"x-api-key": "demo-key-123"}
