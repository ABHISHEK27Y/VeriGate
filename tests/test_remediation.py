"""Regression coverage for the audit remediation."""
# ruff: noqa: PLR2004

import asyncio
import threading

import fakeredis.aioredis
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.cache.namespace import namespace
from app.cache.semantic_cache import SemanticCache
from app.config import Settings, settings
from app.main import create_app
from app.providers import breaker


def test_frozen_app_configuration_and_auth_isolation(monkeypatch):
    one = create_app(settings.model_copy(update={"api_keys": "one"}))
    two = create_app(settings.model_copy(update={"api_keys": "two"}))
    with TestClient(one) as a, TestClient(two) as b:
        monkeypatch.setattr(settings, "api_keys", "changed-after-startup")
        for client, key, other in ((a, "one", "two"), (b, "two", "one")):
            assert (
                client.post(
                    "/v1/chat", json={"prompt": "hello"}, headers={"x-api-key": key}
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/v1/chat", json={"prompt": "hello"}, headers={"x-api-key": other}
                ).status_code
                == 401
            )
        with pytest.raises(ValidationError):
            one.state.config.api_keys = "mutated"


def test_safe_mode_rejects_reordered_roles(client):
    headers = {"x-api-key": "demo-key-123"}
    for prompt, expected in (
        ("alice paid bob 10", "MISS"),
        ("bob paid alice 10", "MISS"),
        ("alice paid bob 10", "HIT"),
    ):
        response = client.post("/v1/chat", json={"prompt": prompt}, headers=headers)
        assert response.json()["cache"] == expected


def test_body_limit_and_bearer_metrics(client):
    response = client.post("/v1/chat", content=b" " * (settings.max_request_bytes + 1))
    assert response.status_code == 413
    assert (
        client.get("/metrics", headers={"authorization": "Bearer test-metrics-token"}).status_code
        == 200
    )
    assert client.get("/live").json() == {"status": "alive"}
    assert client.get("/ready").status_code == 200


def test_namespace_changes_with_model_and_policy(monkeypatch):
    before = namespace()
    monkeypatch.setattr(settings, "openai_model", "different-model")
    assert namespace() != before
    before = namespace()
    monkeypatch.setattr(settings, "cache_epoch", "next")
    assert namespace() != before


@pytest.mark.asyncio
async def test_late_success_cannot_reset_newer_failure():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        older = await breaker.acquire("p", r)
        await breaker.record_failure("p", r)
        await breaker.record_success("p", r, older)
        assert await r.get(breaker._keys("p")[1]) == "1"
        await r.set(breaker._keys("p")[0], "0")
        probe = await breaker.acquire("p", r)
        await r.set(breaker._keys("p")[2], "new-owner")
        await breaker.record_success("p", r, probe)
        assert await r.get(breaker._keys("p")[2]) == "new-owner"
        await breaker.record_failure("p", r, probe)
        assert await r.get(breaker._keys("p")[2]) == "new-owner"
    finally:
        await r.aclose()


def test_permanent_http_errors_do_not_trip_breaker():
    request = httpx.Request("GET", "https://example.invalid")
    for status, expected in ((401, False), (403, False), (429, True), (503, True)):
        error = httpx.HTTPStatusError("test", request=request, response=httpx.Response(status))
        assert breaker.transient(error) is expected


@pytest.mark.asyncio
async def test_cancelled_inference_retains_capacity():
    cache = SemanticCache()
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        release.wait(5)

    task = asyncio.create_task(cache._infer(work))
    while not entered.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cache._inference_gate.locked()
    release.set()
    await asyncio.wait_for(cache._inference_gate.acquire(), timeout=2)
    cache._inference_gate.release()
    await cache.redis.aclose()


@pytest.mark.asyncio
async def test_local_tenants_and_entry_bytes_are_bounded(monkeypatch):
    monkeypatch.setattr(settings, "vector_backend", "inproc")
    monkeypatch.setattr(settings, "cache_match_mode", "semantic")
    monkeypatch.setattr(settings, "max_cached_tenants", 2)
    monkeypatch.setattr(settings, "max_cache_entry_bytes", 10)
    cache = SemanticCache()
    try:
        for tenant in ("a", "b", "c", "d"):
            await cache.lookup("prompt", tenant)
        assert len(cache._index) == 2
        assert len(cache._versions) <= 2
        await cache.store("prompt", "answer-too-large", "a")
        assert await cache.redis.scard(cache._ids_key("a")) == 0
    finally:
        await cache.redis.aclose()


def test_config_rejects_unbounded_storage():
    with pytest.raises(ValidationError):
        Settings(cache_ttl_sec=0)
    with pytest.raises(ValidationError):
        Settings(max_cache_entries_per_tenant=0)


@pytest.mark.asyncio
async def test_request_admission_bounds_active_requests():
    from app.limits import RequestLimitsMiddleware  # noqa: PLC0415

    gateway = create_app(settings.model_copy(update={"max_concurrent_requests": 1}))
    entered, release = asyncio.Event(), asyncio.Event()

    async def downstream(scope, receive, send):
        entered.set()
        await release.wait()

    middleware = RequestLimitsMiddleware(downstream, gateway)

    async def receive():
        return {"type": "http.request", "body": b""}

    messages = []

    async def send(message):
        messages.append(message)

    first = asyncio.create_task(middleware({"type": "http"}, receive, send))
    await entered.wait()
    await middleware({"type": "http"}, receive, send)
    assert messages[0]["status"] == 503
    release.set()
    await first
    assert middleware.active == 0


test_safe_mode_rejects_reordered_roles.config_overrides = {"cache_match_mode": "exact"}


def test_multiprocess_metrics_aggregate_workers(tmp_path):
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}
    for count in (1, 2):
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.metrics import REQUESTS; "
                f"REQUESTS.labels(outcome='multiprocess_test').inc({count})",
            ],
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.metrics import render_metrics; print(render_metrics().decode())",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert 'verigate_requests_total{outcome="multiprocess_test"} 3.0' in result.stdout
