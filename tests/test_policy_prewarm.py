"""Optional NLI prewarming gates startup and readiness."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cache.verifier import NliVerifier
from app.config import Settings
from app.main import create_app

ARTIFACT = (
    Path(__file__).resolve().parents[1] / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
)
HTTP_OK = 200


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        redis_url="",
        cache_match_mode="semantic",
        answer_policy_artifact=str(ARTIFACT),
        answer_policy_prewarm=True,
        embedding_backend="hash",
        vector_backend="inproc",
    )


def test_required_prewarm_completes_before_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(NliVerifier, "prewarm", lambda _self: calls.append("ready"))
    with TestClient(create_app(_settings())) as client:
        assert calls == ["ready"]
        assert client.get("/ready").status_code == HTTP_OK


def test_failed_required_prewarm_prevents_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_self):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(NliVerifier, "prewarm", fail)
    with (
        pytest.raises(RuntimeError, match="model unavailable"),
        TestClient(create_app(_settings())),
    ):
        pass


def test_default_does_not_load_nli_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        NliVerifier,
        "prewarm",
        lambda _self: pytest.fail("default must leave NLI lazy"),
    )
    with TestClient(
        create_app(_settings().model_copy(update={"answer_policy_prewarm": False}))
    ) as client:
        assert client.get("/ready").status_code == HTTP_OK
