"""Frozen paired HTTP/RedisSearch evaluation; controlled provider, no paid calls."""

from __future__ import annotations

import argparse
import asyncio
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
SOURCE = ROOT / "evaluation/runs/technical_applicability_live_20261101_v1"
POLICY = ROOT / "app/cache/artifacts/answer_policy_v1.json"
PORT = 8767
KEY = "applicability-live-eval-only"
URL = "redis://127.0.0.1:6380/0"
VARIANTS = ("applicability_off", "applicability_on")
READY_TIMEOUT_SEC = 300
HTTP_OK = 200


async def _ready(client: httpx.AsyncClient, process: subprocess.Popen) -> tuple[float, dict]:
    start = time.perf_counter()
    while time.perf_counter() - start < READY_TIMEOUT_SEC:
        if process.poll() is not None:
            raise RuntimeError("Gateway exited before readiness")
        try:
            response = await client.get("/ready", timeout=2)
            if response.status_code == HTTP_OK:
                return (time.perf_counter() - start) * 1000, response.json()
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError("Gateway readiness exceeded 300 seconds")


async def _one(  # noqa: PLR0915 - paired live run keeps setup, seeding, and cleanup together
    variant: str, workload: list[dict], output: Path
) -> tuple[list[dict], dict]:
    run_dir = output / variant
    run_dir.mkdir()
    answers = {
        probe["question"]: f"Controlled provider response for {family['family']}."
        for family in workload
        for probe in family["probes"]
    }
    answers_path = run_dir / "provider_answers.json"
    answers_path.write_text(json.dumps(answers, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "ENVIRONMENT": "development",
            "REDIS_URL": URL,
            "CACHE_MATCH_MODE": "semantic",
            "VECTOR_BACKEND": "redisearch",
            "EMBEDDING_BACKEND": "minilm",
            "LLM_PROVIDER": "controlled-eval",
            "EVALUATION_ANSWERS_PATH": str(answers_path),
            "ANSWER_POLICY_ARTIFACT": str(POLICY),
            "ANSWER_POLICY_PREWARM": "true",
            "ANSWER_POLICY_APPLICABILITY_GUARD": str(variant == "applicability_on").lower(),
            "API_KEYS": KEY,
            "CACHE_EPOCH": "applicability-live-20261101-v1",
            "RATE_LIMIT_CAPACITY": "1000",
            "RATE_LIMIT_REFILL_PER_SEC": "1000",
            "DAILY_REQUEST_BUDGET": "0",
            "SHADOW_ENABLED": "false",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    log_path = run_dir / "gateway.log"
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
                str(PORT),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        token = binary_token = None
        redis_client = binary_client = None
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=90) as client:
                startup_ms, ready = await _ready(client, process)
                if ready.get("answer_policy_applicability_guard") != (
                    variant == "applicability_on"
                ):
                    raise AssertionError(
                        "Runtime applicability flag differs from evaluation variant"
                    )
                if any(
                    ready.get(key) != value
                    for key, value in {
                        "cache_match_mode": "semantic",
                        "vector_backend": "redisearch",
                        "embedding_backend": "minilm",
                        "answer_policy_prewarm": True,
                    }.items()
                ) or not ready.get("answer_policy_version"):
                    raise AssertionError(f"Unexpected gateway configuration: {ready}")
                parent_settings = {
                    key: env[key]
                    for key in env
                    if key
                    in {
                        "REDIS_URL",
                        "CACHE_MATCH_MODE",
                        "VECTOR_BACKEND",
                        "EMBEDDING_BACKEND",
                        "LLM_PROVIDER",
                        "EVALUATION_ANSWERS_PATH",
                        "ANSWER_POLICY_ARTIFACT",
                        "ANSWER_POLICY_PREWARM",
                        "ANSWER_POLICY_APPLICABILITY_GUARD",
                        "API_KEYS",
                        "CACHE_EPOCH",
                        "RATE_LIMIT_CAPACITY",
                        "RATE_LIMIT_REFILL_PER_SEC",
                        "DAILY_REQUEST_BUDGET",
                        "SHADOW_ENABLED",
                    }
                }
                os.environ.update(parent_settings)
                token = _runtime.set(snapshot(Settings()))
                redis_client = create_redis()
                binary_client = create_redis(binary=True)
                binary_token = rs.active_client.set(binary_client)
                embedder = Embedder()
                cache = SemanticCache(redis_client, embedder)
                tenant = tenant_id(KEY)
                for family in workload:
                    for probe in family["probes"]:
                        await cache.clear(tenant)
                        for candidate in family["candidates"]:
                            if not await cache.store(
                                candidate["question"], candidate["answer"], tenant
                            ):
                                raise AssertionError("Seeded candidate was not stored")
                        ranked = await rs.knn(embedder.embed(probe["question"]), tenant, k=5)
                        rank_by_query = {item[0]: rank for rank, item in enumerate(ranked, 1)}
                        suitable_ranks = [
                            rank_by_query[family["candidates"][i]["question"]]
                            for i in probe["suitable"]
                            if family["candidates"][i]["question"] in rank_by_query
                        ]
                        started = time.perf_counter()
                        response = await client.post(
                            "/v1/chat",
                            json={"prompt": probe["question"]},
                            headers={"x-api-key": KEY},
                        )
                        http_ms = (time.perf_counter() - started) * 1000
                        body = response.json()
                        selected = body.get("selected_cached_query")
                        suitable_queries = [
                            family["candidates"][i]["question"] for i in probe["suitable"]
                        ]
                        rows.append(
                            {
                                "variant": variant,
                                "family": family["family"],
                                "query": probe["question"],
                                "label": probe["label"],
                                "suitable_queries": suitable_queries,
                                "retrieved_suitable_ranks": suitable_ranks,
                                "retrieval_failure": probe["label"] == "valid"
                                and not suitable_ranks,
                                "http_status": response.status_code,
                                "cache": body.get("cache"),
                                "selected_cached_query": selected,
                                "valid_reuse": body.get("cache") == "HIT"
                                and selected in suitable_queries,
                                "incorrect_accept": body.get("cache") == "HIT"
                                and selected not in suitable_queries,
                                "provider_invoked": body.get("provider_invoked"),
                                "provider": body.get("provider"),
                                "reason": body.get("note"),
                                "candidate_count": body.get("candidate_count"),
                                "selected_rank": body.get("selected_rank"),
                                "candidate_trace": body.get("candidate_trace"),
                                "similarity": body.get("similarity"),
                                "stage_latency_ms": body.get("stage_latency_ms"),
                                "gateway_latency_ms": body.get("latency_ms"),
                                "http_latency_ms": round(http_ms, 3),
                            }
                        )
                        (run_dir / "rows.json").write_text(
                            json.dumps(rows, indent=2) + "\n", encoding="utf-8"
                        )
                await cache.clear(tenant)
        finally:
            if binary_token is not None:
                rs.active_client.reset(binary_token)
            if token is not None:
                _runtime.reset(token)
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
    return rows, {"startup_ms": round(startup_ms, 3), "readiness": ready}


def _summary(rows: list[dict], startup: dict) -> dict:
    result = {}
    for variant in VARIANTS:
        group = [row for row in rows if row["variant"] == variant]
        warm = np.array([row["http_latency_ms"] for row in group[1:]], dtype=float)
        result[variant] = {
            "valid_reuse": sum(row["valid_reuse"] for row in group if row["label"] == "valid"),
            "valid_total": sum(row["label"] == "valid" for row in group),
            "invalid_accepts": sum(
                row["incorrect_accept"] for row in group if row["label"] == "invalid"
            ),
            "invalid_total": sum(row["label"] == "invalid" for row in group),
            "ambiguous_approvals": sum(
                row["cache"] == "HIT" for row in group if row["label"] == "ambiguous"
            ),
            "ambiguous_total": sum(row["label"] == "ambiguous" for row in group),
            "retrieval_failures": sum(row["retrieval_failure"] for row in group),
            "verification_abstentions": sum(
                row["cache"] != "HIT" and bool(row["candidate_trace"]) for row in group
            ),
            "provider_calls": sum(row["provider_invoked"] is True for row in group),
            "first_http_ms": group[0]["http_latency_ms"],
            "warm_http_p50_ms": round(float(np.median(warm)), 3),
            "warm_http_p95_ms": round(float(np.quantile(warm, 0.95)), 3),
            "startup_ms": startup[variant]["startup_ms"],
        }
    return result


async def run(output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    freeze = json.loads((SOURCE / "freeze.json").read_text(encoding="utf-8"))
    source = (SOURCE / "workload.json").read_bytes()
    if hashlib.sha256(source).hexdigest() != freeze["workload_sha256"]:
        raise ValueError("Frozen workload changed")
    workload = json.loads(source)
    output.mkdir(parents=True)
    all_rows, startup = [], {}
    for variant in VARIANTS:
        rows, info = await _one(variant, workload, output)
        all_rows.extend(rows)
        startup[variant] = info
    (output / "summary.json").write_text(
        json.dumps(_summary(all_rows, startup), indent=2) + "\n", encoding="utf-8"
    )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "live-technical-applicability-results-v1",
                "workload_sha256": freeze["workload_sha256"],
                "policy_sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
                "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "redis_url": URL,
                "provider": "controlled-eval; no paid calls",
                "startup": startup,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    asyncio.run(run(parser.parse_args().output))
