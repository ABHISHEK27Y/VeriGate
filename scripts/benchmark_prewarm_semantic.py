"""Compare lazy and required NLI prewarm on one Redis Stack CI runner.

Thirty warm repetitions per case, pinned MiniLM/NLI, delayed mock provider.
Stage counters identify actual NLI inference and model-load requests.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import httpx
import numpy as np

from app.cache import redisearch_store as rs
from app.cache.semantic_cache import SemanticCache
from app.config import Settings, _runtime, snapshot
from app.embeddings import Embedder
from app.identity import tenant_id
from app.redis_client import close_redis, create_redis
from scripts.benchmark_real_semantic import (
    KEY,
    POLICY,
    REJECTED,
    SOURCE,
    VALID,
    _case,
    _ready,
    _request,
)

ROOT = Path(__file__).resolve().parents[1]
TRIALS = 30
CONCURRENT = 8
METRICS_KEY = "benchmark-metrics-key"
METRIC_STAGES = (
    "nli_model_load",
    "nli_tokenization",
    "nli_inference",
    "embedding",
    "retrieval",
    "policy_decision",
)
METRIC_RE = re.compile(
    r'^verigate_stage_latency_seconds_(count|sum)\{stage="([^"]+)"\}\s+([\d.eE+-]+)$'
)


async def _metrics(client: httpx.AsyncClient) -> dict[str, dict[str, float]]:
    response = await client.get("/metrics", headers={"x-metrics-token": METRICS_KEY}, timeout=10)
    response.raise_for_status()
    values: dict[str, dict[str, float]] = {
        stage: {"count": 0.0, "sum": 0.0} for stage in METRIC_STAGES
    }
    for line in response.text.splitlines():
        if match := METRIC_RE.match(line):
            kind, stage, value = match.groups()
            if stage in values:
                values[stage][kind] = float(value)
    return values


async def _sample(  # noqa: PLR0913, PLR0917 - explicit benchmark dimensions
    client: httpx.AsyncClient,
    mode: str,
    trial: int,
    scenario: str,
    prompt: str,
    timeout: float = 90,
) -> dict:
    before = await _metrics(client)
    row = await _request(client, trial, scenario, prompt, timeout)
    after = await _metrics(client)
    row["mode"] = mode
    for stage in METRIC_STAGES:
        row[f"{stage}_calls"] = int(after[stage]["count"] - before[stage]["count"])
        row[f"{stage}_ms"] = round((after[stage]["sum"] - before[stage]["sum"]) * 1000, 3)
    return row


async def _mode(mode: str, output: Path, port: int) -> tuple[float, float, list[dict]]:  # noqa: PLR0915
    env = dict(os.environ)
    env.update(
        {
            "CACHE_MATCH_MODE": "semantic",
            "ANSWER_POLICY_ARTIFACT": str(POLICY),
            "ANSWER_POLICY_PREWARM": "true" if mode == "prewarm" else "false",
            "EMBEDDING_BACKEND": "minilm",
            "VECTOR_BACKEND": "redisearch",
            "LLM_PROVIDER": "mock",
            "API_KEYS": KEY,
            "METRICS_TOKEN": METRICS_KEY,
            "RATE_LIMIT_CAPACITY": "1000",
            "RATE_LIMIT_REFILL_PER_SEC": "1000",
            "CACHE_EPOCH": f"prewarm-{output.name}-{mode}",
            "SHADOW_ENABLED": "false",
        }
    )
    rows: list[dict] = []
    with (output / f"gateway_{mode}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - fixed local module and args
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
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
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                startup_ms = await _ready(client, process)
                startup_model_load_ms = (await _metrics(client))["nli_model_load"]["sum"] * 1000
                runtime_config = Settings(
                    redis_url=env["REDIS_URL"],
                    cache_match_mode="semantic",
                    answer_policy_artifact=str(POLICY),
                    answer_policy_prewarm=mode == "prewarm",
                    embedding_backend="minilm",
                    vector_backend="redisearch",
                    cache_epoch=env["CACHE_EPOCH"],
                )
                runtime_token = _runtime.set(snapshot(runtime_config))
                redis_client = create_redis()
                binary_client = create_redis(binary=True)
                binary_token = rs.active_client.set(binary_client)
                cache = SemanticCache(redis_client, Embedder())
                tenant = tenant_id(KEY)
                valid, rejected = _case(VALID), _case(REJECTED)
                await cache.store(valid["cached_query"], valid["cached_answer"], tenant)
                rows.append(
                    await _sample(client, mode, -1, "first_nli", valid["incoming_query"], 300)
                )

                for trial in range(TRIALS):
                    for scenario, case, prompt in (
                        ("exact_hit", valid, valid["cached_query"]),
                        ("valid_semantic", valid, valid["incoming_query"]),
                        ("rejected_candidate", rejected, rejected["incoming_query"]),
                    ):
                        await cache.clear(tenant)
                        await cache.store(case["cached_query"], case["cached_answer"], tenant)
                        rows.append(await _sample(client, mode, trial, scenario, prompt))
                    await cache.clear(tenant)
                    rows.append(
                        await _sample(
                            client, mode, trial, "cold_miss", f"unique nebula {mode} {trial}"
                        )
                    )
                # One burst per mode; per-request metrics cannot be attributed
                # during concurrency, so these rows record HTTP/call behavior only.
                await cache.clear(tenant)
                burst = await asyncio.gather(
                    *(
                        _request(
                            client, TRIALS, "concurrent_identical", f"unique concurrent {mode}"
                        )
                        for _ in range(CONCURRENT)
                    )
                )
                for row in burst:
                    row["mode"] = mode
                    for stage in METRIC_STAGES:
                        row[f"{stage}_calls"] = ""
                        row[f"{stage}_ms"] = ""
                rows.extend(burst)
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
    return startup_ms, startup_model_load_ms, rows


async def run(output: Path) -> Path:
    if not os.environ.get("REDIS_URL"):
        raise ValueError("REDIS_URL must point to disposable Redis Stack")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    startup: dict[str, float] = {}
    startup_model_load: dict[str, float] = {}
    rows: list[dict] = []
    for mode, port in (("lazy", 8771), ("prewarm", 8772)):
        startup[mode], startup_model_load[mode], mode_rows = await _mode(mode, output, port)
        rows.extend(mode_rows)
    with (output / "requests.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for mode in ("lazy", "prewarm"):
        for scenario in sorted({row["scenario"] for row in rows}):
            group = [row for row in rows if row["mode"] == mode and row["scenario"] == scenario]
            latency = np.asarray([row["http_complete_ms"] for row in group])
            summary.append(
                {
                    "mode": mode,
                    "scenario": scenario,
                    "n": len(group),
                    "hits": sum(row["cache"] == "HIT" for row in group),
                    "provider_calls": sum(row["provider_call"] for row in group),
                    "errors": sum(row["http_status"] != 200 for row in group),  # noqa: PLR2004
                    "nli_inference_calls": sum(
                        int(row["nli_inference_calls"])
                        for row in group
                        if row["nli_inference_calls"] != ""
                    ),
                    "p50_http_ms": round(float(np.median(latency)), 3),
                    "p95_http_ms": round(float(np.quantile(latency, 0.95)), 3),
                }
            )
    with (output / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)
    manifest = {
        "schema_version": "prewarm-live-v1",
        "input_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "policy_artifact_sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_revisions": {
            "minilm": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
            "nli": "a150876415327c80daeff35ca6f68f5ed8cf5c24",
        },
        "trials_per_warm_scenario": TRIALS,
        "startup_ms": startup,
        "startup_nli_model_load_ms": startup_model_load,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "provider": "delayed deterministic mock",
        "outputs": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in ("requests.csv", "summary.csv")
        },
        "limitations": (
            "One runner, two sequential processes, authored selected NQ references; "
            "descriptive latency only"
        ),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if any(row["http_status"] != 200 for row in rows):  # noqa: PLR2004
        raise AssertionError("Benchmark had HTTP errors; inspect saved rows")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    print(asyncio.run(run(parser.parse_args().output)))
