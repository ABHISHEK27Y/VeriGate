"""The fixture reset is isolated to an explicit local demo configuration."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cache.demo_fixtures import FACTS, demo_enabled
from app.config import Settings, _runtime
from app.identity import tenant_id
from app.main import create_app

ARTIFACT = str(
    Path(__file__).resolve().parents[1] / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
)
DEMO = {"x-api-key": "demo-key-123"}
OTHER = {"x-api-key": "other-demo-key"}


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        environment="development",
        redis_url="redis://localhost:6379/0",
        llm_provider="mock",
        cache_match_mode="semantic",
        answer_policy_artifact=ARTIFACT,
        embedding_backend="minilm",
        vector_backend="redisearch",
        api_keys="demo-key-123,other-demo-key",
    ).model_copy(update=overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"environment": "production"},
        {"llm_provider": "gemini"},
        {"cache_match_mode": "exact"},
        {"answer_policy_artifact": ""},
        {"redis_url": ""},
        {"embedding_backend": "hash"},
        {"vector_backend": "inproc"},
        {"api_keys": "other-demo-key"},
    ],
)
def test_restore_guard_requires_explicit_mock_demo(overrides) -> None:
    assert not demo_enabled(_settings(**overrides))


def test_restore_resets_only_designated_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    # Use a fast in-memory backend for the HTTP action; guard combinations above
    # independently cover the real Redis Stack/MiniLM preconditions.
    from app import main  # noqa: PLC0415

    monkeypatch.setattr(main, "demo_enabled", lambda _config: True)
    config = _settings(redis_url="", embedding_backend="hash", vector_backend="inproc")
    with TestClient(create_app(config)) as client:
        other = client.post("/v1/chat", json={"prompt": "other tenant sentinel"}, headers=OTHER)
        assert other.json()["cache"] == "MISS"
        assert client.post("/admin/demo/restore", headers=OTHER).status_code == 404  # noqa: PLR2004
        response = client.post("/admin/demo/restore", headers=DEMO)
        assert response.status_code == 200  # noqa: PLR2004
        assert response.json() == {
            "status": "restored",
            "tenant": "designated-demo",
            "fixtures": len(FACTS),
        }

        async def entries(api_key: str):
            token = _runtime.set(client.app.state.config)
            try:
                cache = client.app.state.semantic_cache
                tenant = tenant_id(api_key)
                await cache.reload(tenant)
                index = cache._t(tenant)
                return list(zip(index["queries"], index["answers"], strict=True))
            finally:
                _runtime.reset(token)

        assert set(client.portal.call(entries, DEMO["x-api-key"])) == set(FACTS)
        assert [query for query, _ in client.portal.call(entries, OTHER["x-api-key"])] == [
            "other tenant sentinel"
        ]
        assert client.post("/admin/demo/restore", headers=DEMO).status_code == 200  # noqa: PLR2004
        assert set(client.portal.call(entries, DEMO["x-api-key"])) == set(FACTS)
        assert [query for query, _ in client.portal.call(entries, OTHER["x-api-key"])] == [
            "other tenant sentinel"
        ]
