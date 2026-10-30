"""Real-provider smoke has a non-spending default and explicit prerequisites."""

from pathlib import Path

import pytest

from app.config import Settings
from scripts import smoke_real_provider


def test_preflight_requires_real_key_redis_and_external_cap() -> None:
    settings = Settings(_env_file=None, redis_url="", llm_provider="mock", api_keys="demo-key-123")
    missing = smoke_real_provider.prerequisites(settings, {})
    assert "REDIS_URL for a disposable Redis instance" in missing
    assert "LLM_PROVIDER=openai or gemini" in missing
    assert "VERIGATE_SMOKE_ACCOUNT_HARD_CAP_CONFIRMED=1" in missing
    assert "VERIGATE_SMOKE_APPROVED_MAX_USD > 0" in missing


def test_smoke_refuses_execution_before_creating_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        smoke_real_provider,
        "create_app",
        lambda _settings: pytest.fail("gateway must not start before prerequisites"),
    )
    with pytest.raises(RuntimeError, match="Smoke prerequisites missing"):
        smoke_real_provider.run(
            tmp_path / "smoke.json", Settings(_env_file=None, redis_url="", llm_provider="mock")
        )
    assert not (tmp_path / "smoke.json").exists()


def test_preflight_accepts_bounded_real_configuration() -> None:
    settings = Settings(
        _env_file=None,
        redis_url="redis://localhost:6379/15",
        llm_provider="openai",
        openai_api_key="test-key",
        api_keys="smoke-key",
    )
    assert (
        smoke_real_provider.prerequisites(
            settings,
            {
                "VERIGATE_SMOKE_ACCOUNT_HARD_CAP_CONFIRMED": "1",
                "VERIGATE_SMOKE_APPROVED_MAX_USD": "0.10",
            },
        )
        == []
    )


def test_smoke_flow_with_free_mock_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Exercise harness sequencing and cleanup without an external call.
    monkeypatch.setattr(smoke_real_provider, "prerequisites", lambda _settings, _env: [])
    monkeypatch.setenv("VERIGATE_SMOKE_APPROVED_MAX_USD", "0.10")
    result = smoke_real_provider.run(
        tmp_path / "smoke.json",
        Settings(_env_file=None, llm_provider="mock", api_keys="smoke-key", redis_url=""),
    )
    assert all(result["checks"].values())
    assert result["max_provider_calls"] == smoke_real_provider.MAX_PROVIDER_CALLS
