"""The loaded answer policy and cache namespace must remain one runtime snapshot."""

from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
from pathlib import Path

import fakeredis.aioredis
from fastapi.testclient import TestClient

from app.cache.namespace import namespace
from app.cache.semantic_cache import SemanticCache
from app.config import Settings, _runtime, snapshot
from app.main import create_app

ARTIFACT = Path(__file__).resolve().parents[1] / "app/cache/artifacts/answer_policy_v1.json"


def test_artifact_change_does_not_change_running_namespace(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(ARTIFACT.read_bytes())
    config = snapshot(Settings(_env_file=None, answer_policy_artifact=str(policy_path)))
    token = _runtime.set(config)
    try:
        cache = SemanticCache(fakeredis.aioredis.FakeRedis(decode_responses=True))
        old_namespace = namespace()
        old_version = cache._answer_policy.version
        changed = json.loads(policy_path.read_text(encoding="utf-8"))
        changed["ambiguity_terms"].append("new-ambiguity")
        changed.pop("version")
        changed["version"] = hashlib.sha256(
            json.dumps(changed, sort_keys=True).encode()
        ).hexdigest()
        policy_path.write_text(json.dumps(changed), encoding="utf-8")
        assert namespace() == old_namespace
        assert cache._answer_policy.version == old_version
    finally:
        _runtime.reset(token)


def test_readiness_reports_verifier_degradation() -> None:
    config = Settings(_env_file=None, answer_policy_artifact=str(ARTIFACT))
    with TestClient(create_app(config)) as client:
        verifier = client.app.state.semantic_cache._policy.verifier
        assert client.get("/ready").json()["answer_verifier_state"] == "lazy"
        verifier.unavailable = True
        verifier.last_failure_category = "RuntimeError"
        response = client.get("/ready")
        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.json()["detail"] == "answer verifier unavailable"
