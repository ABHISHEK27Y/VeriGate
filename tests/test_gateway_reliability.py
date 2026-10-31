"""Regression tests for cache bypass and fail-closed provider handling."""

import asyncio
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.providers.base import Provider
from app.providers.mock import FlakyProvider, MockProvider
from app.providers.registry import ProviderRegistry

HEADERS = {"x-api-key": "demo-key-123"}


class EmptyProvider(Provider):
    name = "empty-test"
    implicit_completion_is_safe = True

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        yield "   "


class PartialProvider(Provider):
    name = "partial-test"
    implicit_completion_is_safe = True

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        yield "partial"
        raise RuntimeError("interrupted upstream")


class LargeProvider(Provider):
    name = "large-test"
    implicit_completion_is_safe = True

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        yield "too long"


class SlowFirstProvider(Provider):
    name = "slow-first-test"
    implicit_completion_is_safe = True

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        await asyncio.sleep(0.2)
        yield "too late"


@pytest.mark.parametrize("endpoint", ["/v1/chat", "/v1/chat/stream"])
def test_first_token_timeout_returns_504_and_is_not_cached(client, endpoint: str) -> None:
    client.app.state.provider_registry = ProviderRegistry(
        providers=(SlowFirstProvider(),), redis=client.app.state.redis
    )
    client.app.state.config = client.app.state.config.model_copy(
        update={"provider_first_token_timeout": 0.02}
    )
    prompt = f"first-token-timeout {endpoint}"
    response = client.post(endpoint, json={"prompt": prompt}, headers=HEADERS)
    assert response.status_code == 504  # noqa: PLR2004
    assert response.json()["detail"] == "upstream timeout"
    again = client.post(endpoint, json={"prompt": prompt}, headers=HEADERS)
    assert again.status_code == 504  # noqa: PLR2004


def test_bypass_skips_cache_read_and_write(client) -> None:
    prompt = "Which poet wrote the first poem in this test?"
    first = client.post("/v1/chat", json={"prompt": prompt, "cache_bypass": True}, headers=HEADERS)
    assert first.json()["cache"] == "BYPASS"
    assert first.json()["provider"] == "mock"
    second = client.post("/v1/chat", json={"prompt": prompt}, headers=HEADERS)
    assert second.json()["cache"] == "MISS"
    third = client.post("/v1/chat", json={"prompt": prompt, "cache_bypass": True}, headers=HEADERS)
    assert third.json()["cache"] == "BYPASS"
    fourth = client.post("/v1/chat", json={"prompt": prompt}, headers=HEADERS)
    assert fourth.json()["cache"] == "HIT"


def test_unsupported_generation_fields_are_rejected(client) -> None:
    for payload in (
        {"prompt": "hello", "temperature": 0.7},
        {"messages": [{"role": "user", "content": "hello", "name": "Alice"}]},
    ):
        response = client.post("/v1/chat", json=payload, headers=HEADERS)
        assert response.status_code == 422  # noqa: PLR2004


def test_authentication_precedes_body_parsing(client) -> None:
    response = client.post("/v1/chat", content=b"{" * 70000)
    assert response.status_code == 401  # noqa: PLR2004


def test_production_health_hides_configuration_without_api_key(client) -> None:
    client.app.state.config = client.app.state.config.model_copy(
        update={"environment": "production"}
    )
    public = client.get("/health")
    assert public.json() == {"status": "ok"}
    assert client.get("/admin/config").status_code == 401  # noqa: PLR2004
    private = client.get("/admin/config", headers=HEADERS)
    assert private.json()["cache_match_mode"] in {"exact", "semantic"}


def test_cache_write_failure_preserves_generated_json_answer(client, monkeypatch) -> None:
    async def fail_store(*_args):
        raise OSError("cache unavailable")

    monkeypatch.setattr(client.app.state.semantic_cache, "store", fail_store)
    response = client.post("/v1/chat", json={"prompt": "unique write failure"}, headers=HEADERS)
    assert response.status_code == 200  # noqa: PLR2004
    assert response.json()["provider"] == "mock"
    assert response.json()["answer"]


def test_cache_lookup_failure_falls_back_to_provider(client, monkeypatch) -> None:
    async def fail_lookup(*_args):
        raise OSError("cache unavailable")

    monkeypatch.setattr(client.app.state.semantic_cache, "lookup", fail_lookup)
    response = client.post("/v1/chat", json={"prompt": "unique lookup failure"}, headers=HEADERS)
    assert response.status_code == 200  # noqa: PLR2004
    assert response.json()["cache"] == "MISS"
    assert response.json()["note"] == "cache_unavailable"


def test_cache_write_failure_completes_stream(client, monkeypatch) -> None:
    async def fail_store(*_args):
        raise OSError("cache unavailable")

    monkeypatch.setattr(client.app.state.semantic_cache, "store", fail_store)
    response = client.post(
        "/v1/chat/stream", json={"prompt": "unique stream write failure"}, headers=HEADERS
    )
    assert response.status_code == 200  # noqa: PLR2004
    assert "data: [DONE]" in response.text
    assert "event: error" not in response.text


@pytest.mark.parametrize("endpoint", ["/v1/chat", "/v1/chat/stream"])
def test_empty_provider_answer_is_not_cached(client, endpoint: str) -> None:
    client.app.state.provider_registry = ProviderRegistry(
        providers=(EmptyProvider(),), redis=client.app.state.redis
    )
    response = client.post(endpoint, json={"prompt": "unique empty answer"}, headers=HEADERS)
    if endpoint.endswith("stream"):
        assert "event: error" in response.text
        assert "data: [DONE]" not in response.text
    else:
        assert response.status_code == 502  # noqa: PLR2004
    again = client.post("/v1/chat", json={"prompt": "unique empty answer"}, headers=HEADERS)
    assert again.status_code == 502  # noqa: PLR2004


def test_cascade_fallback_answer_is_not_cached_under_failed_route(client) -> None:
    client.app.state.provider_registry = ProviderRegistry(
        providers=(),
        cascade={
            "cheap": FlakyProvider(fail=True),
            "strong": MockProvider(name_override="strong-test"),
        },
        redis=client.app.state.redis,
    )
    prompt = "who painted this unique test portrait"
    first = client.post("/v1/chat", json={"prompt": prompt}, headers=HEADERS)
    second = client.post("/v1/chat", json={"prompt": prompt}, headers=HEADERS)
    assert first.json()["cache"] == second.json()["cache"] == "MISS"
    assert first.json()["provider"] == second.json()["provider"] == "strong-test"


test_cascade_fallback_answer_is_not_cached_under_failed_route.config_overrides = {  # type: ignore[attr-defined]
    "cascade_enabled": True,
}


def test_admission_redis_failure_fails_closed(client, monkeypatch) -> None:
    async def fail_allow(*_args):
        raise OSError("Redis unavailable")

    monkeypatch.setattr(client.app.state.rate_limiter, "allow", fail_allow)
    response = client.post("/v1/chat", json={"prompt": "must not call provider"}, headers=HEADERS)
    assert response.status_code == 503  # noqa: PLR2004
    assert response.json()["detail"] == "admission unavailable"


def test_budget_redis_failure_fails_closed(client, monkeypatch) -> None:
    from app import main  # noqa: PLC0415

    async def fail_budget(*_args):
        raise OSError("Redis unavailable")

    monkeypatch.setattr(main, "budget_check_and_count", fail_budget)
    response = client.post("/v1/chat", json={"prompt": "must not call provider"}, headers=HEADERS)
    assert response.status_code == 503  # noqa: PLR2004
    assert response.json()["detail"] == "admission unavailable"


def test_partial_stream_never_caches(client) -> None:
    client.app.state.provider_registry = ProviderRegistry(
        providers=(PartialProvider(),), redis=client.app.state.redis
    )
    prompt = "unique partial stream case"
    streamed = client.post("/v1/chat/stream", json={"prompt": prompt}, headers=HEADERS)
    assert "event: error" in streamed.text
    assert "data: [DONE]" not in streamed.text
    client.app.state.provider_registry = ProviderRegistry(
        providers=(MockProvider(),), redis=client.app.state.redis
    )
    following = client.post("/v1/chat", json={"prompt": prompt}, headers=HEADERS)
    assert following.json()["cache"] == "MISS"


@pytest.mark.parametrize("endpoint", ["/v1/chat", "/v1/chat/stream"])
def test_response_size_error_is_distinct_and_uncached(client, endpoint: str) -> None:
    client.app.state.provider_registry = ProviderRegistry(
        providers=(LargeProvider(),), redis=client.app.state.redis
    )
    client.app.state.config = client.app.state.config.model_copy(update={"max_response_chars": 3})
    response = client.post(endpoint, json={"prompt": "unique too large"}, headers=HEADERS)
    if endpoint.endswith("stream"):
        assert "upstream response too large" in response.text
        assert "data: [DONE]" not in response.text
    else:
        assert response.status_code == 502  # noqa: PLR2004
        assert response.json()["detail"] == "upstream response too large"


def test_partial_startup_closes_first_redis_connection(monkeypatch) -> None:
    from app import main  # noqa: PLC0415

    class TrackedRedis(fakeredis.aioredis.FakeRedis):
        closed = False

        async def aclose(self) -> None:
            self.closed = True
            await super().aclose()

    first = TrackedRedis(decode_responses=True)
    calls = 0

    def failing_create_redis(*, binary=False):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("second connection failed")
        return first

    monkeypatch.setattr(main, "create_redis", failing_create_redis)
    with (
        pytest.raises(RuntimeError, match="second connection failed"),
        TestClient(create_app(settings)),
    ):
        pass
    assert first.closed
