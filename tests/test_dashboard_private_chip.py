"""Normal dashboard requests defer scope choice to the authenticated server policy."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_organization_scopes import ALICE, directory_file, settings_for

from app.main import create_app

EXPECTED_ORG_CHIPS = 2


def test_normal_dashboard_omits_scope_and_developer_override_is_explicit(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    if os.environ.get("VERIGATE_BROWSER_TEST") != "1":
        pytest.skip("Run opt-in browser regression with VERIGATE_BROWSER_TEST=1")
    playwright = pytest.importorskip("playwright.sync_api")
    path = tmp_path / "organizations-demo.json"
    config = settings_for(path, "dashboard-private-chip-salt")
    directory_file(path, config.api_key_salt)
    directory = json.loads(path.read_text(encoding="utf-8"))
    directory["organizations"]["example"]["application_defaults"] = {
        "developer-tool": "engineering"
    }
    path.write_text(json.dumps(directory), encoding="utf-8")
    observed = []
    observed_stream = []

    with TestClient(create_app(config)) as client, playwright.sync_playwright() as engine:
        try:
            browser = engine.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium unavailable for browser regression: {type(exc).__name__}")
        try:
            page = browser.new_page()

            def forward(route):
                request = route.request
                if request.url.endswith("/v1/chat"):
                    observed.append(request.post_data_json)
                if request.url.endswith("/v1/chat/stream"):
                    observed_stream.append(request.post_data_json)
                path_and_query = request.url.removeprefix("http://verigate.test")
                headers = {"x-api-key": request.headers.get("x-api-key", "")}
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
            page.get_by_text("shared factual fixture").wait_for()
            assert page.locator("#dev-overrides").is_hidden()
            assert page.locator("#chips .chip").count() == EXPECTED_ORG_CHIPS
            page.locator("#query").fill("Explain how Python decorators work.")
            page.locator("#ask").click()
            page.locator("#result").wait_for(state="visible")
            assert observed[-1] == {"prompt": "Explain how Python decorators work."}
            assert page.locator("#rlat-label").text_content() == "gateway time (after admission)"
            page.get_by_text("How this request was handled").click()
            assert page.locator("#rscope").inner_text() == "workspace"
            assert page.locator("#rstoragewhy").inner_text().startswith("workspace ·")
            assert page.get_by_text("How this request was handled").count() == 1
            page.screenshot(path=str(tmp_path / "dashboard.png"), full_page=True)
            page.goto("http://verigate.test/ui?developer=1")
            page.locator("#apikey").fill(ALICE)
            page.locator("#apikey").dispatch_event("change")
            assert page.locator("#dev-overrides").is_visible()
            page.locator("#dev-overrides summary").click()
            page.locator("#scope").select_option("private")
            page.locator("#query").fill("Explain Python functions.")
            page.locator("#ask").click()
            page.locator("#result").wait_for(state="visible")
            assert observed[-1] == {
                "prompt": "Explain Python functions.",
                "cache_scope": "private",
            }
            page.locator("#scope").select_option("auto")
            page.locator("#stream-response").check()
            page.locator("#query").fill("Explain how Python generators work.")
            page.locator("#ask").click()
            page.get_by_text(
                "[mock:mock-example-mock] Answer to: Explain how Python generators work."
            ).wait_for()
            assert observed_stream[-1] == {"prompt": "Explain how Python generators work."}
            assert page.locator("#rbadge").inner_text() == "MISS"
            assert (
                page.locator("#rlat-label").text_content()
                == "stream gateway time (after handler entry)"
            )
            page.get_by_text("How this request was handled").click()
            assert page.locator("#rscope").inner_text() == "workspace"
            assert page.locator("#rstorage").inner_text() == "stored"
        finally:
            browser.close()
