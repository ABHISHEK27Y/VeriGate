"""The development private chip must send its scope with the panel collapsed."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_organization_scopes import ALICE, directory_file, settings_for

from app.main import create_app


def test_private_chip_posts_private_scope_with_panel_collapsed(tmp_path: Path) -> None:
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
                    content_type=response.headers.get("content-type", "text/plain"),
                    body=response.content,
                )

            page.route("http://verigate.test/**", forward)
            page.goto("http://verigate.test/ui")
            page.locator("#apikey").fill(ALICE)
            page.locator("#apikey").dispatch_event("change")
            page.get_by_text("private isolation").wait_for()
            assert not page.locator("#dev-overrides").evaluate("element => element.open")
            page.locator("#chips .chip").nth(2).click()
            page.locator("#result").wait_for(state="visible")
            assert observed[-1]["cache_scope"] == "private"
            assert page.locator("#rscope").inner_text() == "private"
        finally:
            browser.close()
