"""Honest end-to-end HTTP demonstration of the controlled-answer gateway path.

Boots a *disposable* gateway (fakeredis, hash embeddings, exact matching) with the
development ``controlled-eval`` provider and a small, explicitly labelled answer
map, then drives real HTTP requests to show:

  * employee A MISS -> labelled controlled answer generated and stored;
  * an authorized colleague reusing that stored answer (HIT, shared);
  * private isolation and cross-organization isolation;
  * a provider failure (prompt absent from the controlled map) leaving no cache write;
  * TTL expiry of a stored answer.

Scope note: this exercises the *internal exact shortcut* and the authorization /
storage / isolation machinery with real labelled answers over real HTTP. It does
NOT exercise the MiniLM + NLI semantic paraphrase path, which needs model
downloads (unavailable in a network-restricted sandbox); that path runs in CI.
The controlled answer map lives entirely in the provider and never reaches
retrieval or acceptance. This is a controlled demonstration, not accuracy,
provider-cost, or production-readiness evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ALICE = "example-alice-key-12345"
CAROL = "example-carol-key-12345"
DAVE = "other-dave-key-123456"
SALT = "controlled-http-demo-salt"
WORKSPACE = {"cache_scope": "workspace", "workspace": "engineering"}
TTL_EXPIRY_MAX_SEC = 5  # at or below this, the demo waits out the TTL to show expiry

ANSWERS = {
    "Explain how Python decorators work.": (
        "A Python decorator wraps a callable to add behaviour without editing its source."
    ),
    "Explain how Python context managers work.": (
        "A context manager defines __enter__/__exit__ so a with-block sets up and tears down state."
    ),
    "Summarize my personal on-call runbook.": (
        "An on-call runbook lists the ordered steps to triage, mitigate, and escalate an incident."
    ),
}


def _digest(key: str) -> str:
    return hmac.new(SALT.encode(), key.encode(), hashlib.sha256).hexdigest()


def _write_inputs(tmp: Path) -> tuple[Path, Path]:
    answers = tmp / "controlled_answers.json"
    answers.write_text(json.dumps(ANSWERS, indent=2), encoding="utf-8")
    directory = tmp / "organizations-controlled.json"
    directory.write_text(
        json.dumps(
            {
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
                        "key_digest": _digest(key),
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
        ),
        encoding="utf-8",
    )
    return directory, answers


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _boot(directory: Path, answers: Path, port: int, ttl: int) -> subprocess.Popen:
    env = {
        **os.environ,
        "ENVIRONMENT": "development",
        "API_KEYS": "",
        "API_KEY_SALT": SALT,
        "ORGANIZATION_CONFIG_PATH": str(directory),
        "LLM_PROVIDER": "controlled-eval",
        "EVALUATION_ANSWERS_PATH": str(answers),
        "CACHE_MATCH_MODE": "exact",
        "EMBEDDING_BACKEND": "hash",
        "VECTOR_BACKEND": "inproc",
        "REDIS_URL": "",
        "CACHE_TTL_SEC": str(ttl),
        "METRICS_TOKEN": "demo-metrics-token",
    }
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    return subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_ready(client: httpx.Client) -> dict:
    for _ in range(100):
        try:
            response = client.get("/ready")
            if response.status_code == httpx.codes.OK:
                ready: dict = response.json()
                return ready
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("gateway did not become ready")


FIELDS = (
    "cache",
    "answer",
    "provider",
    "intended_provider",
    "provider_invoked",
    "organization_id",
    "subject_id",
    "cache_scope",
    "lookup_scope",
    "provider_profile",
    "candidate_count",
    "storage_outcome",
    "storage_scope",
    "latency_ms",
)


def _ask(client: httpx.Client, key: str, prompt: str, **extra) -> dict:
    response = client.post("/v1/chat", headers={"x-api-key": key}, json={"prompt": prompt, **extra})
    if response.status_code != httpx.codes.OK:
        return {"http_status": response.status_code, "detail": response.json().get("detail")}
    body = response.json()
    return {"http_status": 200, **{field: body.get(field) for field in FIELDS}}


def run(output: Path, ttl: int) -> None:
    if output.exists():
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        directory, answers = _write_inputs(tmp)
        port = _free_port()
        proc = _boot(directory, answers, port, ttl)
        rows: dict[str, object] = {}
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
                ready = _wait_ready(client)
                decorators = next(iter(ANSWERS))
                rows["01_alice_miss_generates_and_stores"] = _ask(
                    client, ALICE, decorators, **WORKSPACE
                )
                rows["02_carol_colleague_shared_reuse"] = _ask(
                    client, CAROL, decorators, **WORKSPACE
                )
                # A different (also labelled) question is a separate decision, not a false reuse.
                rows["03_carol_other_question_miss"] = _ask(
                    client, CAROL, "Explain how Python context managers work.", **WORKSPACE
                )
                # Private isolation (explicit private; this org defaults to the workspace).
                rows["04_alice_private_store"] = _ask(
                    client, ALICE, "Summarize my personal on-call runbook.", cache_scope="private"
                )
                rows["05_carol_private_isolated_miss"] = _ask(
                    client, CAROL, "Summarize my personal on-call runbook.", cache_scope="private"
                )
                # Cross-organization isolation and workspace denial.
                rows["06_dave_cross_org_miss"] = _ask(client, DAVE, decorators)
                rows["07_dave_workspace_denied"] = _ask(client, DAVE, decorators, **WORKSPACE)
                # Provider failure: prompt absent from the controlled map -> upstream error.
                rows["08_absent_prompt_provider_failure"] = _ask(
                    client, ALICE, "What will the stock market do tomorrow?", **WORKSPACE
                )
                rows["09_absent_prompt_still_miss_no_cache_write"] = _ask(
                    client, ALICE, "What will the stock market do tomorrow?", **WORKSPACE
                )
                # TTL expiry: a stored answer is gone after its finite lifetime.
                if ttl <= TTL_EXPIRY_MAX_SEC:
                    time.sleep(ttl + 1.5)
                    rows["10_decorators_after_ttl_expiry"] = _ask(
                        client, CAROL, decorators, **WORKSPACE
                    )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "kind": "controlled_eval_exact_http_demo_not_accuracy_or_billing_evidence",
                "note": (
                    "Exact-match internal shortcut path with labelled controlled answers over "
                    "real HTTP. MiniLM+NLI semantic paraphrase path is not exercised here "
                    "(models unavailable in this sandbox); it runs in CI."
                ),
                "python": platform.python_version(),
                "cache_ttl_sec": ttl,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "ready": ready,
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"saved {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ttl", type=int, default=3, help="CACHE_TTL_SEC (<=5 exercises expiry)")
    args = parser.parse_args()
    run(args.output, args.ttl)


if __name__ == "__main__":
    main()
