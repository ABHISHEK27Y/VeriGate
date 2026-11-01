"""Capture dashboard screenshots from the controlled-eval demonstration.

Development-only. Drives the real dashboard against an in-process gateway that
uses the controlled-eval provider (labelled fixtures) so the screenshots show
genuine returned evidence with the corrected answer-source label -- a controlled
fixture is shown as "controlled evaluation fixture", never "generated answer".
These are exact-shortcut controlled-demo screenshots; they are not accuracy,
provider-cost, or production-readiness evidence, and the semantic candidate
trace (which needs model downloads) is not populated here.

Usage: VERIGATE_BROWSER_TEST is not required; Chromium must be available.
  PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python -I scripts/capture_dashboard_shots.py OUTDIR
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app.config import Settings
from app.main import create_app

ALICE = "example-alice-key-12345"
SALT = "dashboard-shot-salt"
FIXTURE_Q = "Explain how Python decorators work."
FIXTURE_A = "A Python decorator wraps a callable to add behaviour without editing its source."


def _digest(key: str) -> str:
    return hmac.new(SALT.encode(), key.encode(), hashlib.sha256).hexdigest()


def _config(tmp: Path) -> Settings:
    answers = tmp / "answers.json"
    answers.write_text(json.dumps({FIXTURE_Q: FIXTURE_A}), encoding="utf-8")
    directory = tmp / "org.json"
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
                        "key_digest": _digest(ALICE),
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
        _env_file=None,  # type: ignore[call-arg]  # pydantic-settings init arg
        environment="development",
        api_keys="",
        api_key_salt=SALT,
        organization_config_path=str(directory),
        llm_provider="controlled-eval",
        evaluation_answers_path=str(answers),
        cache_match_mode="exact",
        embedding_backend="hash",
        vector_backend="inproc",
    )


def run(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    tmp = outdir / "_cfg"
    tmp.mkdir(exist_ok=True)
    config = _config(tmp)
    with TestClient(create_app(config)) as client, sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1600})

        def forward(route):
            request = route.request
            path_and_query = request.url.removeprefix("http://verigate.test")
            headers = {"x-api-key": request.headers.get("x-api-key", "")}
            if "content-type" in request.headers:
                headers["content-type"] = request.headers["content-type"]
            response = client.request(
                request.method, path_and_query, headers=headers, content=request.post_data
            )
            route.fulfill(
                status=response.status_code, headers=dict(response.headers), body=response.content
            )

        page.route("http://verigate.test/**", forward)
        page.goto("http://verigate.test/ui")
        page.locator("#apikey").fill(ALICE)
        page.locator("#apikey").dispatch_event("change")
        page.screenshot(path=str(outdir / "ui_controlled_hero.png"), full_page=True)

        # MISS: controlled fixture generated and stored; source label corrected.
        page.locator("#query").fill(FIXTURE_Q)
        page.locator("#ask").click()
        page.locator("#result").wait_for(state="visible")
        page.get_by_text(FIXTURE_A).wait_for()
        page.wait_for_function("document.getElementById('rbadge').textContent.endsWith('MISS')")
        page.locator("summary", has_text="How this request was handled").click()
        page.screenshot(path=str(outdir / "ui_controlled_miss.png"), full_page=True)
        source_miss = page.locator("#rsource").inner_text()

        # HIT: the authorized reuse of the stored answer, labelled as a cache delivery.
        page.locator("#query").fill(FIXTURE_Q)
        page.locator("#ask").click()
        page.wait_for_function("document.getElementById('rbadge').textContent.endsWith('HIT')")
        page.screenshot(path=str(outdir / "ui_controlled_hit.png"), full_page=True)
        source_hit = page.locator("#rsource").inner_text()
        browser.close()

    (outdir / "capture_manifest.json").write_text(
        json.dumps(
            {
                "kind": "controlled_eval_exact_dashboard_screenshots",
                "miss_answer_source_label": source_miss,
                "hit_answer_source_label": source_hit,
                "fixture_answer": FIXTURE_A,
                "note": "Exact-shortcut controlled demo; not accuracy/billing evidence.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"saved screenshots to {outdir}: miss_source={source_miss!r} hit_source={source_hit!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outdir", type=Path)
    args = parser.parse_args()
    if sys.flags.isolated:
        pass
    run(args.outdir)


if __name__ == "__main__":
    main()
