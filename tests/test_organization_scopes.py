"""Organization identities and authorized cache scopes through the HTTP gateway."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as gateway_main
from app.config import Settings
from app.main import create_app
from app.organization import OrganizationDirectory
from app.providers.mock import MockProvider

ARTIFACT = Path(__file__).resolve().parents[1] / "app/cache/artifacts/answer_policy_v1.json"

ALICE = "example-alice-key-12345"
CAROL = "example-carol-key-12345"
DAVE = "other-dave-key-123456"
ROTATED = "example-alice-new-key-12345"


def digest(key: str, salt: str) -> str:
    return hmac.new(salt.encode(), key.encode(), hashlib.sha256).hexdigest()


def directory_file(path: Path, salt: str) -> None:
    raw = {
        "schema_version": 1,
        "organizations": {
            "example": {
                "default_profile": "example-mock",
                "workspaces": {
                    "engineering": {
                        "members": ["alice", "carol"],
                        "trusted_applications": ["developer-tool"],
                    }
                },
            },
            "other": {"default_profile": "other-mock", "workspaces": {}},
        },
        "provider_profiles": {
            "example-mock": {"provider": "mock"},
            "other-mock": {"provider": "mock"},
        },
        "credentials": [
            {
                "key_digest": digest(key, salt),
                "organization_id": org,
                "subject_id": subject,
                "application_id": "developer-tool",
                "permissions": ["cache:shared"] if org == "example" else [],
                "status": "active",
            }
            for key, org, subject in (
                (ALICE, "example", "alice"),
                (CAROL, "example", "carol"),
                (DAVE, "other", "dave"),
            )
        ],
    }
    path.write_text(json.dumps(raw), encoding="utf-8")


def settings_for(path: Path, salt: str) -> Settings:
    return Settings(
        _env_file=None,
        api_keys="",
        api_key_salt=salt,
        organization_config_path=str(path),
        llm_provider="mock",
        cache_match_mode="exact",
        embedding_backend="hash",
        vector_backend="inproc",
    )


def ask(client: TestClient, key: str, prompt: str, **extra):
    return client.post("/v1/chat", json={"prompt": prompt, **extra}, headers={"x-api-key": key})


def test_shared_private_cross_org_and_forged_scope(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "scope-test-salt")
    directory_file(path, config.api_key_salt)
    with TestClient(create_app(config)) as client:
        shared = {"cache_scope": "workspace", "workspace": "engineering"}
        prompt = "Explain Redis cache eviction."
        first = ask(client, ALICE, prompt, **shared)
        assert first.status_code == HTTPStatus.OK
        assert first.json()["cache"] == "MISS"
        assert first.json()["cache_scope"] == "workspace"
        assert first.json()["provider_profile"] == "example-mock"
        reused = ask(client, CAROL, prompt, **shared)
        assert reused.json()["cache"] == "HIT"
        assert reused.json()["answer"] == first.json()["answer"]
        assert reused.json()["subject_id"] == "carol"
        assert "exact_lookup" in reused.json()["stage_latency_ms"]
        assert reused.json()["storage_outcome"] == "cache_hit"
        occupancy = client.get(
            "/admin/cache/occupancy?scope=workspace&workspace=engineering",
            headers={"x-api-key": CAROL},
        )
        assert occupancy.status_code == HTTPStatus.OK
        assert occupancy.json()["entries"] == 1
        assert (
            client.get(
                "/admin/cache/occupancy?scope=workspace&workspace=engineering",
                headers={"x-api-key": DAVE},
            ).status_code
            == HTTPStatus.FORBIDDEN
        )
        private = ask(client, ALICE, prompt)
        assert private.json()["cache"] == "MISS"
        assert ask(client, CAROL, prompt).json()["cache"] == "MISS"
        assert ask(client, DAVE, prompt).json()["cache"] == "MISS"
        assert ask(client, DAVE, prompt, **shared).status_code == HTTPStatus.FORBIDDEN
        cleared = client.post("/admin/cache/clear", headers={"x-api-key": ALICE})
        assert cleared.status_code == HTTPStatus.OK
        assert ask(client, CAROL, prompt, **shared).json()["cache"] == "HIT"
        assert ask(client, ALICE, prompt).json()["cache"] == "MISS"
        assert (
            ask(client, CAROL, prompt, organization_id="other", **shared).status_code
            == HTTPStatus.UNPROCESSABLE_ENTITY
        )
        assert (
            ask(client, CAROL, prompt, cache_scope="workspace", workspace="forged").status_code
            == HTTPStatus.FORBIDDEN
        )
        # A personal password question is private, while an actual secret value is no-store.
        sensitive = ask(client, ALICE, "Explain my Redis password", **shared).json()
        assert sensitive["cache_scope"] == "private"
        assert sensitive["cache"] == "MISS"
        assert sensitive["storage_eligibility"] == "private_only"
        assert sensitive["storage_outcome"] == "stored"
        assert ask(client, ALICE, "Explain my Redis password", **shared).json()["cache"] == "HIT"
        assert ask(client, CAROL, "Explain my Redis password", **shared).json()["cache"] == "MISS"
        actual_secret = ask(client, ALICE, "password=SuperSecret123", **shared).json()
        assert actual_secret["cache"] == "BYPASS"
        assert actual_secret["storage_eligibility"] == "no_store"


def test_server_default_shares_generic_technical_requests_without_scope_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "automatic-scope-test-salt")
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["organizations"]["example"]["application_defaults"] = {"developer-tool": "engineering"}
    path.write_text(json.dumps(raw), encoding="utf-8")
    with TestClient(create_app(config)) as client:
        prompt = "Explain why a token bucket limits request bursts."
        first = ask(client, ALICE, prompt).json()
        assert first["cache_scope"] == "workspace"
        assert first["scope_reason"] == "authorized_default"
        assert first["storage_eligibility"] == "shared_eligible"
        assert first["storage_outcome"] == "stored"
        assert first["scope_policy_version"]
        reused = ask(client, CAROL, prompt).json()
        assert reused["cache"] == "HIT"
        assert reused["answer"] == first["answer"]
        assert ask(client, DAVE, prompt).json()["cache"] == "MISS"
        assert ask(client, ALICE, prompt, cache_scope="private").json()["cache"] == "MISS"
        assert ask(client, CAROL, prompt, cache_scope="private").json()["cache"] == "MISS"
        assert ask(client, ALICE, prompt, cache_scope="none").json()["cache"] == "BYPASS"


def test_application_default_never_grants_missing_shared_permission(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "default-without-permission-salt")
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["organizations"]["example"]["application_defaults"] = {"developer-tool": "engineering"}
    raw["credentials"][0]["permissions"] = []
    path.write_text(json.dumps(raw), encoding="utf-8")
    with TestClient(create_app(config)) as client:
        prompt = "Explain Redis cache eviction."
        private = ask(client, ALICE, prompt)
        assert private.status_code == HTTPStatus.OK
        assert private.json()["cache_scope"] == "private"
        assert private.json()["scope_reason"] == "shared_not_authorized"
        assert ask(client, CAROL, prompt).json()["cache"] == "MISS"
        assert (
            ask(client, ALICE, prompt, cache_scope="workspace", workspace="engineering").status_code
            == HTTPStatus.FORBIDDEN
        )


def test_private_only_response_stores_only_in_employee_scope(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "private-response-test-salt")
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["organizations"]["example"]["application_defaults"] = {"developer-tool": "engineering"}
    path.write_text(json.dumps(raw), encoding="utf-8")
    with TestClient(create_app(config)) as client:
        prompt = "Explain our account settings."
        first = ask(client, ALICE, prompt).json()
        assert first["cache_scope"] == "private"
        assert first["storage_outcome"] == "stored"
        assert ask(client, ALICE, prompt).json()["cache"] == "HIT"
        assert ask(client, CAROL, prompt).json()["cache"] == "MISS"


def test_shared_request_with_private_response_reuses_only_for_originator(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "response-downgrade-test-salt")
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["organizations"]["example"]["application_defaults"] = {"developer-tool": "engineering"}
    path.write_text(json.dumps(raw), encoding="utf-8")

    async def private_answer(self, _prompt):
        yield "Our account uses a private internal setting."

    monkeypatch.setattr(MockProvider, "stream", private_answer)
    with TestClient(create_app(config)) as client:
        prompt = "Explain the service configuration."
        first = ask(client, ALICE, prompt).json()
        assert first["cache"] == "MISS"
        assert first["cache_scope"] == "workspace"
        assert first["request_eligibility"] == "shared_eligible"
        assert first["response_eligibility"] == "private_only"
        assert first["storage_scope"] == "private"
        assert first["storage_outcome"] == "stored"
        again = ask(client, ALICE, prompt).json()
        assert again["cache"] == "HIT"
        assert again["lookup_scope"] == "private"
        assert again["provider"] == "cache"
        other = ask(client, CAROL, prompt).json()
        assert other["cache"] == "MISS"
        assert other["provider"] == "mock-example-mock"


def test_stream_reports_response_downgrade_and_private_overlay(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "stream-downgrade-test-salt")
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["organizations"]["example"]["application_defaults"] = {"developer-tool": "engineering"}
    path.write_text(json.dumps(raw), encoding="utf-8")

    async def private_answer(self, _prompt):
        yield "Our account uses a private internal setting."

    monkeypatch.setattr(MockProvider, "stream", private_answer)
    prompt = "Explain the service configuration."
    with TestClient(create_app(config)) as client:
        first = client.post(
            "/v1/chat/stream", json={"prompt": prompt}, headers={"x-api-key": ALICE}
        )
        assert first.headers["x-cache-scope"] == "workspace"
        assert '"storage_scope": "private"' in first.text
        assert '"response_eligibility": "private_only"' in first.text
        again = client.post(
            "/v1/chat/stream", json={"prompt": prompt}, headers={"x-api-key": ALICE}
        )
        assert again.headers["x-provider"] == "cache"
        assert again.headers["x-cache-scope"] == "private"
        assert '"provider_invoked": false' in again.text
        other = client.post(
            "/v1/chat/stream", json={"prompt": prompt}, headers={"x-api-key": CAROL}
        )
        assert other.headers["x-provider"] == "mock-example-mock"


def test_redisearch_private_overlay_reads_binary_vector_safely(tmp_path: Path, monkeypatch) -> None:
    if not os.environ.get("REDIS_URL") or os.environ.get("VECTOR_BACKEND") != "redisearch":
        pytest.skip("Requires isolated Redis Stack test configuration")
    path = tmp_path / "organizations.json"
    base = settings_for(path, "redisearch-overlay-test-salt")
    config = base.model_copy(
        update={
            "redis_url": os.environ["REDIS_URL"],
            "vector_backend": "redisearch",
            "cache_match_mode": "semantic",
        }
    )
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["organizations"]["example"]["application_defaults"] = {"developer-tool": "engineering"}
    path.write_text(json.dumps(raw), encoding="utf-8")

    async def private_answer(self, _prompt):
        yield "Our account uses a private internal setting."

    monkeypatch.setattr(MockProvider, "stream", private_answer)
    with TestClient(create_app(config)) as client:
        prompt = "Explain the service configuration."
        first = ask(client, ALICE, prompt).json()
        assert first["cache"] == "MISS"
        assert first["storage_scope"] == "private"
        again = ask(client, ALICE, prompt).json()
        assert again["cache"] == "HIT"
        assert again["lookup_scope"] == "private"
        assert ask(client, CAROL, prompt).json()["cache"] == "MISS"


def test_legacy_no_store_request_cannot_be_cached(client) -> None:
    headers = {"x-api-key": "demo-key-123"}
    for _ in range(2):
        response = client.post(
            "/v1/chat",
            headers=headers,
            json={"prompt": "Explain token buckets", "cache_scope": "none"},
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["cache"] == "BYPASS"
        assert response.json()["storage_eligibility"] == "no_store"


def test_multiple_authorized_workspaces_without_default_remain_private(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "ambiguous-workspace-test-salt")
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["organizations"]["example"]["workspaces"]["operations"] = {
        "members": ["alice", "carol"],
        "trusted_applications": ["developer-tool"],
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    with TestClient(create_app(config)) as client:
        result = ask(client, ALICE, "Explain retry backoff.").json()
        assert result["cache_scope"] == "private"
        assert result["scope_reason"] == "no_default_workspace"
        assert ask(client, CAROL, "Explain retry backoff.").json()["cache"] == "MISS"


def test_rotation_and_revocation_preserve_subject_scope(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "rotation-test-salt")
    directory_file(path, config.api_key_salt)
    before = OrganizationDirectory(config)
    alice = before.resolve(ALICE)
    assert alice is not None
    raw = json.loads(path.read_text(encoding="utf-8"))
    rotated = {**raw["credentials"][0], "key_digest": digest(ROTATED, config.api_key_salt)}
    raw["credentials"][0]["status"] = "revoked"
    raw["credentials"].append(rotated)
    path.write_text(json.dumps(raw), encoding="utf-8")
    after = OrganizationDirectory(config)
    new_alice = after.resolve(ROTATED)
    assert new_alice is not None
    assert after.resolve(ALICE) is None
    assert before.scoped_tenant(alice, "private", "", "mock-example-mock") == after.scoped_tenant(
        new_alice, "private", "", "mock-example-mock"
    )
    with TestClient(create_app(config)) as client:
        assert (
            ask(client, ALICE, "Explain Python decorators").status_code == HTTPStatus.UNAUTHORIZED
        )
        assert ask(client, ROTATED, "Explain Python decorators").status_code == HTTPStatus.OK


def test_live_revocation_and_rotation_without_cache_orphan(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "live-rotation-test-salt")
    config.daily_request_budget = 1
    directory_file(path, config.api_key_salt)
    with TestClient(create_app(config)) as client:
        first = ask(client, ALICE, "Explain Python decorators").json()
        assert first["cache"] == "MISS"
        raw = json.loads(path.read_text(encoding="utf-8"))
        replacement = {
            **raw["credentials"][0],
            "key_digest": digest(ROTATED, config.api_key_salt),
        }
        raw["credentials"][0]["status"] = "revoked"
        raw["credentials"].append(replacement)
        updated = tmp_path / "updated.json"
        updated.write_text(json.dumps(raw), encoding="utf-8")
        updated.replace(path)
        assert (
            ask(client, ALICE, "Explain Python decorators").status_code == HTTPStatus.UNAUTHORIZED
        )
        rotated = ask(client, ROTATED, "Explain Python decorators").json()
        assert rotated["cache"] == "HIT"
        assert rotated["subject_id"] == "alice"
        assert ask(client, ROTATED, "Explain SQL joins").status_code == HTTPStatus.TOO_MANY_REQUESTS


def test_revocation_during_hit_lookup_prevents_serve(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "serve-boundary-test-salt")
    directory_file(path, config.api_key_salt)
    with TestClient(create_app(config)) as client:
        assert ask(client, ALICE, "Explain Python decorators").json()["cache"] == "MISS"
        original = client.app.state.semantic_cache.lookup

        async def revoke_after_lookup(query: str, tenant: str):
            result = await original(query, tenant)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["credentials"][0]["status"] = "revoked"
            replacement = tmp_path / "revoked.json"
            replacement.write_text(json.dumps(raw), encoding="utf-8")
            replacement.replace(path)
            return result

        client.app.state.semantic_cache.lookup = revoke_after_lookup
        response = ask(client, ALICE, "Explain Python decorators")
        assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_revocation_after_generation_prevents_shared_write(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "generation-revocation-test-salt")
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["organizations"]["example"]["application_defaults"] = {"developer-tool": "engineering"}
    path.write_text(json.dumps(raw), encoding="utf-8")
    original = gateway_main._generate_answer

    async def revoke_after_generation(prompt, request, registry):
        generated = await original(prompt, request, registry)
        updated = json.loads(path.read_text(encoding="utf-8"))
        updated["credentials"][0]["status"] = "revoked"
        replacement = tmp_path / "revoked-after-generation.json"
        replacement.write_text(json.dumps(updated), encoding="utf-8")
        replacement.replace(path)
        return generated

    with TestClient(create_app(config)) as client:
        monkeypatch.setattr(gateway_main, "_generate_answer", revoke_after_generation)
        result = ask(client, ALICE, "Explain deterministic retries.")
        assert result.status_code == HTTPStatus.OK
        assert result.json()["storage_outcome"] == "credential_changed_no_store"
        assert (
            ask(client, ALICE, "Explain deterministic retries.").status_code
            == HTTPStatus.UNAUTHORIZED
        )
        assert ask(client, CAROL, "Explain deterministic retries.").json()["cache"] == "MISS"


def test_concurrent_profiles_are_isolated(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "concurrent-test-salt")
    directory_file(path, config.api_key_salt)
    with TestClient(create_app(config)) as client, ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ask, client, key, "Explain SQL joins") for key in (ALICE, DAVE)]
        responses = [future.result() for future in futures]
        assert all(response.status_code == HTTPStatus.OK for response in responses)
        assert responses[0].json()["provider"] == "mock-example-mock"
        assert responses[1].json()["provider"] == "mock-other-mock"
        assert responses[0].json()["organization_id"] == "example"
        assert responses[1].json()["organization_id"] == "other"
        assert responses[0].json()["cache"] == responses[1].json()["cache"] == "MISS"


def test_semantic_retrieval_excludes_unauthorized_private_candidate(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "semantic-scope-test-salt")
    config.cache_match_mode = "semantic"
    config.answer_policy_artifact = str(ARTIFACT)
    directory_file(path, config.api_key_salt)
    with TestClient(create_app(config)) as client:
        first = ask(client, ALICE, "Explain Python decorators").json()
        assert first["cache"] == "MISS"
        other = ask(client, CAROL, "Explain Python decorators").json()
        assert other["cache"] == "MISS"
        assert other["candidate_count"] == 0
        assert other["note"] == "empty_cache"


def test_full_private_cache_keeps_provider_answer(tmp_path: Path) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "capacity-http-test-salt")
    config.private_cache_byte_limit = 10
    directory_file(path, config.api_key_salt)
    with TestClient(create_app(config)) as client:
        result = ask(client, ALICE, "Explain Python decorators")
        assert result.status_code == HTTPStatus.OK
        assert result.json()["provider"] == "mock-example-mock"
        assert result.json()["storage_outcome"] == "ineligible_or_full"
        assert ask(client, ALICE, "Explain Python decorators").json()["cache"] == "MISS"


def test_missing_profile_secret_is_explicit_and_readiness_fails(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "organizations.json"
    config = settings_for(path, "missing-secret-test-salt")
    directory_file(path, config.api_key_salt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["provider_profiles"]["example-mock"] = {
        "provider": "openai",
        "secret_env": "VERIGATE_TEST_MISSING_PROVIDER_SECRET",
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.delenv("VERIGATE_TEST_MISSING_PROVIDER_SECRET", raising=False)
    with TestClient(create_app(config)) as client:
        assert client.get("/ready").status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert (
            ask(client, ALICE, "Explain Python decorators").status_code
            == HTTPStatus.SERVICE_UNAVAILABLE
        )
