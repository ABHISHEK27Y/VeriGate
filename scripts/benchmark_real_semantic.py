"""Repeat live MiniLM + NLI gateway cases against a disposable Redis Stack DB.

The NQ cases are diagnostic references, not independently reviewed correctness.
No paid provider is called. Run with REDIS_URL and an unused output directory.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import httpx
import numpy as np

from app.cache import redisearch_store as rs
from app.cache.semantic_cache import SemanticCache
from app.config import Settings, _runtime, snapshot
from app.embeddings import Embedder
from app.identity import tenant_id
from app.redis_client import close_redis, create_redis

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
SOURCE = ROOT / "evaluation" / "runs" / "nq_dev_close_neighbors_v5" / "decisions.csv"
KEY = "semantic-benchmark-key"
VALID = "nq-dev:1511:2705"
REJECTED = "nq-dev:1702:3418"
TRIALS = 3
CONCURRENT = 8
STARTUP_TIMEOUT_SEC = 360
HTTP_OK = 200


def _case(family: str) -> dict[str, str]:
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        return next(
            row
            for row in csv.DictReader(stream)
            if row["family_id"] == family and row["system"] == "answer_aware_v1"
        )


async def _ready(client: httpx.AsyncClient, process: subprocess.Popen) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < STARTUP_TIMEOUT_SEC:
        if process.poll() is not None:
            raise RuntimeError("Gateway exited before readiness")
        try:
            response = await client.get("/health", timeout=2)
            if response.status_code == HTTP_OK:
                return (time.perf_counter() - started) * 1000
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError("Gateway cold startup exceeded 360 seconds")


async def _request(
    client: httpx.AsyncClient, trial: int, scenario: str, prompt: str, timeout: float = 90
) -> dict:
    started = time.perf_counter()
    try:
        response = await client.post(
            "/v1/chat", json={"prompt": prompt}, headers={"x-api-key": KEY}, timeout=timeout
        )
        body = response.json()
        status = response.status_code
    except (httpx.HTTPError, ValueError) as exc:
        body = {"cache": "ERROR", "provider": "", "note": type(exc).__name__}
        status = 0
    note = str(body.get("note", ""))
    return {
        "trial": trial,
        "scenario": scenario,
        "http_status": status,
        "cache": body.get("cache", "ERROR"),
        "note": note,
        "provider": body.get("provider", ""),
        "provider_call": status == HTTP_OK
        and body.get("provider") != "cache"
        and not note.startswith("coalesced:"),
        "http_complete_ms": round((time.perf_counter() - started) * 1000, 3),
    }


async def run(output: Path) -> Path:  # noqa: PLR0912, PLR0915 - one frozen benchmark run
    if not os.environ.get("REDIS_URL"):
        raise ValueError("REDIS_URL must point to disposable Redis Stack")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    env = dict(os.environ)
    env.update(
        {
            "CACHE_MATCH_MODE": "semantic",
            "ANSWER_POLICY_ARTIFACT": str(POLICY),
            "EMBEDDING_BACKEND": "minilm",
            "VECTOR_BACKEND": "redisearch",
            "LLM_PROVIDER": "mock",
            "API_KEYS": KEY,
            "RATE_LIMIT_CAPACITY": "1000",
            "RATE_LIMIT_REFILL_PER_SEC": "1000",
            "CACHE_EPOCH": f"real-semantic-{output.name}",
            "SHADOW_ENABLED": "false",
        }
    )
    log_path = output / "gateway.log"
    rows: list[dict] = []
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - fixed local module and args
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8766",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        redis_client = None
        binary_client = None
        runtime_token = None
        binary_token = None
        try:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8766") as client:
                cold_startup_ms = await _ready(client, process)
                # Parent owns its own connections and uses exactly the server config.
                os.environ.update(
                    {
                        key: env[key]
                        for key in env
                        if key
                        in {
                            "CACHE_MATCH_MODE",
                            "ANSWER_POLICY_ARTIFACT",
                            "EMBEDDING_BACKEND",
                            "VECTOR_BACKEND",
                            "LLM_PROVIDER",
                            "API_KEYS",
                            "RATE_LIMIT_CAPACITY",
                            "RATE_LIMIT_REFILL_PER_SEC",
                            "CACHE_EPOCH",
                            "SHADOW_ENABLED",
                        }
                    }
                )
                runtime_token = _runtime.set(snapshot(Settings()))
                redis_client = create_redis()
                binary_client = create_redis(binary=True)
                binary_token = rs.active_client.set(binary_client)
                cache = SemanticCache(redis_client, Embedder())
                tenant = tenant_id(KEY)
                valid, rejected = _case(VALID), _case(REJECTED)

                # First NLI decision is cold and excluded from the warm distribution.
                await cache.store(valid["cached_query"], valid["cached_answer"], tenant)
                first = await _request(client, -1, "cold_first_nli", valid["incoming_query"], 300)
                rows.append(first)
                await cache.clear(tenant)

                # The cold request may exhaust the verifier budget while its model
                # keeps loading in a protected worker. Establish warm state through
                # observed HTTP decisions, and retain every warmup abstention.
                warmup_succeeded = False
                for attempt in range(8):
                    await cache.clear(tenant)
                    await cache.store(valid["cached_query"], valid["cached_answer"], tenant)
                    warmup = await _request(
                        client, attempt, "warmup_valid_semantic", valid["incoming_query"]
                    )
                    rows.append(warmup)
                    if warmup["cache"] == "HIT":
                        warmup_succeeded = True
                        break

                for trial in range(TRIALS):
                    for scenario, case, prompt in (
                        ("exact_hit", valid, valid["cached_query"]),
                        ("valid_semantic", valid, valid["incoming_query"]),
                        ("rejected_candidate", rejected, rejected["incoming_query"]),
                    ):
                        await cache.clear(tenant)
                        await cache.store(case["cached_query"], case["cached_answer"], tenant)
                        rows.append(await _request(client, trial, scenario, prompt))
                    await cache.clear(tenant)
                    rows.append(
                        await _request(client, trial, "cold_miss", f"unique nebula {trial}")
                    )
                    await cache.clear(tenant)
                    rows.extend(
                        await asyncio.gather(
                            *(
                                _request(
                                    client,
                                    trial,
                                    "concurrent_identical",
                                    f"unique concurrent {trial}",
                                )
                                for _ in range(CONCURRENT)
                            )
                        )
                    )
        finally:
            if binary_token is not None:
                rs.active_client.reset(binary_token)
            if runtime_token is not None:
                _runtime.reset(runtime_token)
            if redis_client is not None:
                await close_redis(redis_client)
            if binary_client is not None:
                await close_redis(binary_client)
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    summary = []
    for scenario in sorted({row["scenario"] for row in rows}):
        group = [row for row in rows if row["scenario"] == scenario]
        latencies = np.asarray([row["http_complete_ms"] for row in group])
        summary.append(
            {
                "scenario": scenario,
                "n": len(group),
                "hits": sum(row["cache"] == "HIT" for row in group),
                "provider_calls": sum(row["provider_call"] for row in group),
                "errors": sum(row["http_status"] != HTTP_OK for row in group),
                "p50_http_complete_ms": round(float(np.median(latencies)), 3),
                "p95_http_complete_ms": round(float(np.quantile(latencies, 0.95)), 3),
            }
        )
    for name, data in (("requests.csv", rows), ("summary.csv", summary)):
        with (output / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(data)
    manifest = {
        "schema_version": "real-semantic-live-v1",
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "policy_artifact_sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "nli_model": "cross-encoder/nli-deberta-v3-xsmall",
        "nli_revision": "a150876415327c80daeff35ca6f68f5ed8cf5c24",
        "trials": TRIALS,
        "warmup_attempts": sum(row["scenario"] == "warmup_valid_semantic" for row in rows),
        "warmup_succeeded": warmup_succeeded,
        "cold_startup_ms": round(cold_startup_ms, 3),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "outputs": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in ("requests.csv", "summary.csv")
        },
        "limitations": (
            "NQ reference proxy, deterministic mock provider, three trials on one CI runner"
        ),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    expected = {
        "exact_hit": "HIT",
        "valid_semantic": "HIT",
        "rejected_candidate": "MISS",
        "cold_miss": "MISS",
    }
    if not warmup_succeeded or any(
        row["http_status"] != HTTP_OK
        or (row["scenario"] in expected and row["cache"] != expected[row["scenario"]])
        for row in rows
    ):
        raise AssertionError("Real semantic benchmark response mismatch; inspect saved rows")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    print(asyncio.run(run(parser.parse_args().output)))
