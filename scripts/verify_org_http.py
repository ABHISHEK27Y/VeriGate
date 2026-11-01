"""Exercise the running mock organization gateway without persisting credentials.

Requires scripts/seed_org_demo.py to have reset and seeded the workspace first.
The directory rotation is restored atomically even if an assertion fails.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx

from app.identity import hash_api_key

ALICE = "example-alice-key-12345"
CAROL = "example-carol-key-12345"
DAVE = "other-dave-key-123456"
ROTATED = "example-alice-rotated-key-12345"
WORKSPACE = {"cache_scope": "workspace", "workspace": "engineering"}
FACT = "A Python decorator wraps a function to add behavior without changing its source."
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_UNPROCESSABLE = 422


def _record(name: str, response: httpx.Response) -> dict:
    payload = response.json()
    if response.status_code != HTTP_OK:
        return {"case": name, "http_status": response.status_code, "detail": payload.get("detail")}
    fields = (
        "answer",
        "cache",
        "provider",
        "organization_id",
        "subject_id",
        "cache_scope",
        "provider_profile",
        "candidate_count",
        "selected_rank",
        "similarity",
        "nli_score",
        "verifier_invoked",
        "note",
        "storage_outcome",
        "latency_ms",
        "stage_latency_ms",
    )
    return {
        "case": name,
        "http_status": response.status_code,
        **{k: payload.get(k) for k in fields},
    }


async def run(base: str, config_path: Path, output: Path) -> None:  # noqa: PLR0915
    if output.exists():
        raise FileExistsError(output)
    original = config_path.read_bytes()
    directory = json.loads(original)
    if (
        directory["credentials"][0]["key_digest"] != hash_api_key(ALICE)
        or directory["credentials"][0]["status"] != "active"
    ):
        raise ValueError("Demo directory and local salt do not match the named fixture")
    rows = []

    async with httpx.AsyncClient(base_url=base, timeout=45) as client:
        ready = (await client.get("/ready")).json()
        assert ready["cache_match_mode"] == "semantic"
        assert ready["embedding_backend"] == "minilm"
        assert ready["answer_policy_prewarm"] is True
        for key in (ALICE, CAROL, DAVE):
            cleared = await client.post("/admin/cache/clear", headers={"x-api-key": key})
            assert cleared.status_code == HTTP_OK

        async def ask(name: str, key: str, prompt: str, **kwargs) -> httpx.Response:
            response = await client.post(
                "/v1/chat",
                headers={"x-api-key": key},
                json={"prompt": prompt, **kwargs},
            )
            rows.append(_record(name, response))
            return response

        shared = await ask(
            "carol_shared_paraphrase",
            CAROL,
            "Explain how Python decorators work.",
            **WORKSPACE,
        )
        assert shared.status_code == HTTP_OK
        assert shared.json()["cache"] == "HIT" and shared.json()["answer"] == FACT
        assert shared.json()["selected_rank"] == 1
        assert shared.json()["provider"] == "cache"

        private = await ask("alice_private_store", ALICE, "Explain Python functions.")
        assert private.json()["cache"] == "MISS"
        assert private.json()["storage_outcome"] == "stored"
        carol_private = await ask("carol_private_isolated", CAROL, "Explain Python functions.")
        assert carol_private.json()["cache"] == "MISS"
        assert carol_private.json()["candidate_count"] == 0
        dave_private = await ask("dave_org_isolated", DAVE, "Explain Python functions.")
        assert dave_private.json()["cache"] == "MISS"
        assert dave_private.json()["provider_profile"] == "other-mock"
        assert (
            await ask("dave_workspace_denied", DAVE, "Explain Python functions.", **WORKSPACE)
        ).status_code == HTTP_FORBIDDEN
        assert (
            await ask(
                "forged_org_denied",
                CAROL,
                "Explain Python functions.",
                organization_id="other",
                **WORKSPACE,
            )
        ).status_code == HTTP_UNPROCESSABLE

        a_route, d_route = await asyncio.gather(
            ask("alice_route", ALICE, "Explain Python iterators."),
            ask("dave_route", DAVE, "Explain Redis clusters."),
        )
        assert a_route.json()["provider"] == "mock-example-mock"
        assert d_route.json()["provider"] == "mock-other-mock"
        assert a_route.json()["organization_id"] == "example"
        assert d_route.json()["organization_id"] == "other"

        a_parallel, c_parallel = await asyncio.gather(
            ask("alice_private_parallel", ALICE, "Explain Python behavior in build 73192."),
            ask("carol_private_parallel", CAROL, "Explain Python behavior in build 73192."),
        )
        for response in (a_parallel, c_parallel):
            assert response.json()["cache"] == "MISS"
            assert response.json()["provider"] == "mock-example-mock"
            assert not response.json()["note"].startswith("coalesced:")

        assert (await ask("carol_private_repeat", CAROL, "Explain Python functions.")).json()[
            "cache"
        ] == "HIT"
        clear = await client.post("/admin/cache/clear", headers={"x-api-key": ALICE})
        assert clear.status_code == HTTP_OK
        assert (await ask("carol_survives_alice_clear", CAROL, "Explain Python functions.")).json()[
            "cache"
        ] == "HIT"
        assert (await ask("alice_private_after_clear", ALICE, "Explain Python functions.")).json()[
            "cache"
        ] == "MISS"

        rotated = {**directory["credentials"][0], "key_digest": hash_api_key(ROTATED)}
        directory["credentials"][0]["status"] = "revoked"
        directory["credentials"].append(rotated)
        replacement = config_path.with_suffix(".rotating")
        try:
            replacement.write_text(json.dumps(directory), encoding="utf-8")
            replacement.replace(config_path)
            assert (
                await ask(
                    "revoked_alice_denied", ALICE, "How do Python decorators work?", **WORKSPACE
                )
            ).status_code == HTTP_UNAUTHORIZED
            after = await ask(
                "rotated_identity_shared_hit",
                ROTATED,
                "How do Python decorators work?",
                **WORKSPACE,
            )
            assert after.json()["cache"] == "HIT"
            assert after.json()["subject_id"] == "alice"
            assert after.json()["answer"] == FACT
        finally:
            restore = config_path.with_suffix(".restoring")
            restore.write_bytes(original)
            restore.replace(config_path)
            replacement.unlink(missing_ok=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "kind": "mock_provider_http_demo_not_accuracy_or_billing_evidence",
                "directory_sha256": hashlib.sha256(original).hexdigest(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "ready": ready,
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--directory", type=Path, default=Path("config/organizations-demo.json"))
    args = parser.parse_args()
    asyncio.run(run(args.base, args.directory, args.output))


if __name__ == "__main__":
    main()
