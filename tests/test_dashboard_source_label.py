"""The dashboard must never present a controlled-eval fixture as a generated answer.

Regression for the confirmed answer-source label defect: a response produced by
the development controlled-eval provider (a fixed fixture) was labelled
"generated answer". The source label must be derived from the actual provider
metadata -- "controlled evaluation fixture" for controlled-eval, "cached answer"
for a cache delivery -- never inferred from the answer text. Opt-in browser test.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ALICE = "example-alice-key-12345"
FIXTURE_Q = "Explain how Python decorators work."
FIXTURE_A = "A Python decorator wraps a callable to add behaviour without editing its source."


def _digest(key: str, salt: str) -> str:
    return hmac.new(salt.encode(), key.encode(), hashlib.sha256).hexdigest()


def _config(tmp_path: Path) -> Settings:
    salt = "source-label-salt"
    directory = tmp_path / "organizations-controlled.json"
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({FIXTURE_Q: FIXTURE_A}), encoding="utf-8")
    directory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "organizations": {
                    "example": {
                        "default_profile": "example-eval",
                        "workspaces": {
                            "engineering": {
                                "members": ["alice"],
                                "trusted_applications": ["developer-tool"],
                            }
                        },
                        "application_defaults": {"developer-tool": "engineering"},
                    }
                },
                "provider_profiles": {"example-eval": {"provider": "controlled-eval"}},
                "credentials": [
                    {
                        "key_digest": _digest(ALICE, salt),
                        "organization_id": "example",
                        "subject_id": "alice",
                        "application_id": "developer-tool",
                        "permissions": ["cache:shared"],
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
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
        redis_url="",  # isolated fakeredis even when a CI job exports a shared REDIS_URL
    )


def test_controlled_fixture_is_not_shown_as_generated(tmp_path: Path) -> None:
    if os.environ.get("VERIGATE_BROWSER_TEST") != "1":
        pytest.skip("Run opt-in browser regression with VERIGATE_BROWSER_TEST=1")
    playwright = pytest.importorskip("playwright.sync_api")
    config = _config(tmp_path)

    with TestClient(create_app(config)) as client, playwright.sync_playwright() as engine:
        try:
            browser = engine.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium unavailable for browser regression: {type(exc).__name__}")
        try:
            page = browser.new_page()

            def forward(route):
                request = route.request
                path_and_query = request.url.removeprefix("http://verigate.test")
                headers = {"x-api-key": request.headers.get("x-api-key", "")}
                if "content-type" in request.headers:
                    headers["content-type"] = request.headers["content-type"]
                response = client.request(
                    request.method,
                    path_and_query,
                    headers=headers,
                    content=request.post_data,
                )
                route.fulfill(
                    status=response.status_code,
                    headers=dict(response.headers),
                    body=response.content,
                )

            page.route("http://verigate.test/**", forward)
            page.goto("http://verigate.test/ui")
            page.locator("#apikey").fill(ALICE)
            page.locator("#apikey").dispatch_event("change")

            # First ask: a genuine MISS served by the controlled-eval fixture provider.
            page.locator("#query").fill(FIXTURE_Q)
            page.locator("#ask").click()
            page.locator("#result").wait_for(state="visible")
            page.get_by_text(FIXTURE_A).wait_for()
            page.wait_for_function("document.getElementById('rbadge').textContent.endsWith('MISS')")
            source = page.locator("#rsource").inner_text()
            assert source == "controlled evaluation fixture", source
            assert "generated" not in source.lower()
            # #rprov lives inside the collapsed details; text_content reads hidden nodes.
            assert page.locator("#rprov").text_content() == "controlled-eval-example-eval"

            # Second ask of the same question: a cache HIT is labelled as a cache delivery,
            # not as the original fixture or a generated answer.
            page.locator("#query").fill(FIXTURE_Q)
            page.locator("#ask").click()
            page.wait_for_function("document.getElementById('rbadge').textContent.endsWith('HIT')")
            hit_source = page.locator("#rsource").inner_text()
            assert hit_source == "cached answer", hit_source
            assert "generated" not in hit_source.lower()
        finally:
            browser.close()
