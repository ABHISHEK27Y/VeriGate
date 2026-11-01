"""Controlled-answer provider on the organization path (development-only).

The controlled-eval provider lets an honest HTTP demonstration generate a real
labelled answer on a genuine MISS, store it under the authorized workspace, and
have a colleague reuse it -- instead of the generic mock echoing the prompt back
(the F23 confound). The answer map lives outside retrieval/acceptance; it never
reaches the matching code. These checks exercise the wiring with exact matching
(no model download), so the semantic/NLI path is covered elsewhere in CI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from http import HTTPStatus
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ALICE = "example-alice-key-12345"
CAROL = "example-carol-key-12345"
DAVE = "other-dave-key-123456"
WORKSPACE = {"cache_scope": "workspace", "workspace": "engineering"}

DECORATOR_Q = "Explain how Python decorators work."
DECORATOR_A = "A Python decorator wraps a callable to add behaviour without editing its source."
PRIVATE_Q = "Summarize my personal deployment runbook."
PRIVATE_A = "A deployment runbook lists the ordered steps to release and roll back a service."


def _digest(key: str, salt: str) -> str:
    return hmac.new(salt.encode(), key.encode(), hashlib.sha256).hexdigest()


def _directory_file(path: Path, salt: str) -> None:
    raw = {
        "schema_version": 1,
        "organizations": {
            "example": {
                "default_profile": "example-eval",
                "workspaces": {
                    "engineering": {
                        "members": ["alice", "carol"],
                        "trusted_applications": ["developer-tool"],
                    }
                },
                "application_defaults": {"developer-tool": "engineering"},
            },
            "other": {"default_profile": "other-eval", "workspaces": {}},
        },
        "provider_profiles": {
            "example-eval": {"provider": "controlled-eval"},
            "other-eval": {"provider": "controlled-eval"},
        },
        "credentials": [
            {
                "key_digest": _digest(key, salt),
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


def _settings(tmp_path: Path, salt: str) -> Settings:
    directory = tmp_path / "organizations-controlled.json"
    answers = tmp_path / "controlled_answers.json"
    answers.write_text(
        json.dumps({DECORATOR_Q: DECORATOR_A, PRIVATE_Q: PRIVATE_A}),
        encoding="utf-8",
    )
    _directory_file(directory, salt)
    return Settings(
        _env_file=None,
        environment="development",
        api_keys="",
        api_key_salt=salt,
        organization_config_path=str(directory),
        llm_provider="controlled-eval",
        evaluation_answers_path=str(answers),
        cache_match_mode="exact",
        embedding_backend="hash",
        vector_backend="inproc",
    )


def _ask(client: TestClient, key: str, prompt: str, **extra):
    return client.post("/v1/chat", json={"prompt": prompt, **extra}, headers={"x-api-key": key})


def test_controlled_answer_generated_on_miss_is_shared_with_authorized_colleague(
    tmp_path: Path,
) -> None:
    config = _settings(tmp_path, "controlled-eval-salt")
    with TestClient(create_app(config)) as client:
        first = _ask(client, ALICE, DECORATOR_Q, **WORKSPACE)
        assert first.status_code == HTTPStatus.OK
        body = first.json()
        assert body["cache"] == "MISS"
        # The stored answer is the labelled controlled answer, not a mock echo.
        assert body["answer"] == DECORATOR_A
        assert body["provider"] == "controlled-eval-example-eval"
        assert body["storage_outcome"] == "stored"
        assert body["cache_scope"] == "workspace"

        reused = _ask(client, CAROL, DECORATOR_Q, **WORKSPACE)
        assert reused.status_code == HTTPStatus.OK
        reuse = reused.json()
        assert reuse["cache"] == "HIT"
        assert reuse["answer"] == DECORATOR_A
        assert reuse["provider"] == "cache"
        assert reuse["subject_id"] == "carol"
        assert reuse["storage_outcome"] == "cache_hit"


def test_controlled_answer_isolated_across_org_and_private_scope(tmp_path: Path) -> None:
    config = _settings(tmp_path, "controlled-eval-salt")
    with TestClient(create_app(config)) as client:
        assert _ask(client, ALICE, DECORATOR_Q, **WORKSPACE).json()["cache"] == "MISS"
        # Dave is in a different organization; the shared entry must not leak.
        dave = _ask(client, DAVE, DECORATOR_Q)
        assert dave.json()["cache"] == "MISS"
        assert dave.json()["organization_id"] == "other"
        assert dave.json()["provider"] == "controlled-eval-other-eval"
        # Dave cannot request the example workspace at all.
        assert _ask(client, DAVE, DECORATOR_Q, **WORKSPACE).status_code == HTTPStatus.FORBIDDEN

        # A private answer is isolated to the employee who generated it.
        # (This organization sets engineering as the application default, so the
        # private scope is requested explicitly to exercise isolation.)
        alice_private = _ask(client, ALICE, PRIVATE_Q, cache_scope="private")
        assert alice_private.json()["cache"] == "MISS"
        assert alice_private.json()["answer"] == PRIVATE_A
        assert alice_private.json()["cache_scope"] == "private"
        assert alice_private.json()["storage_outcome"] == "stored"
        carol_private = _ask(client, CAROL, PRIVATE_Q, cache_scope="private")
        assert carol_private.json()["cache"] == "MISS"
        assert carol_private.json()["candidate_count"] == 0
