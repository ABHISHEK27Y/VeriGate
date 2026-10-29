"""Small live HTTP/Redis Stack benchmark with a deterministic delayed mock provider.

This measures gateway behavior on CI hardware, not real-provider quality or cost.
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

ROOT = Path(__file__).resolve().parents[1]
HEADERS_A = {"x-api-key": "benchmark-a"}
HEADERS_B = {"x-api-key": "benchmark-b"}


async def _ready(client: httpx.AsyncClient, process: subprocess.Popen) -> None:
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError("Gateway exited before readiness")
        try:
            response = await client.get("/ready", timeout=2)
            if response.status_code == 200:  # noqa: PLR2004
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError("Gateway did not become ready")


async def _scenario(  # noqa: PLR0913 - explicit benchmark dimensions
    client: httpx.AsyncClient,
    mode: str,
    scenario: str,
    prompt: str,
    *,
    headers: dict[str, str] | None = None,
    bypass: bool = False,
) -> dict:
    started = time.perf_counter_ns()
    response = await client.post(
        "/v1/chat",
        json={"prompt": prompt, "cache_bypass": bypass},
        headers=headers or HEADERS_A,
        timeout=40,
    )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    response.raise_for_status()
    result = response.json()
    return {
        "mode": mode,
        "scenario": scenario,
        "cache": result["cache"],
        "provider": result["provider"],
        "fallback_used": result["fallback_used"],
        "note": result["note"],
        "http_complete_ms": round(elapsed_ms, 3),
        "mock_provider_invoked": result["provider"] != "cache",
    }


async def _measure_mode(mode: str, output: Path) -> list[dict]:
    env = dict(os.environ)
    env.update(
        {
            "REDIS_URL": os.environ["REDIS_URL"],
            "CACHE_MATCH_MODE": mode,
            "EMBEDDING_BACKEND": "hash",
            "VECTOR_BACKEND": "redisearch",
            "LLM_PROVIDER": "mock",
            "API_KEYS": "benchmark-a,benchmark-b",
            "RATE_LIMIT_CAPACITY": "1000",
            "RATE_LIMIT_REFILL_PER_SEC": "1000",
            "CACHE_SIMILARITY_BASE": "0.5",
            "CACHE_EPOCH": f"live-benchmark-{output.name}-{mode}",
        }
    )
    log_path = output / f"gateway_{mode}.log"
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
                "8765",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8765") as client:
                await _ready(client, process)
                # Warm process, Redis connection and hash embedder outside measured rows.
                await _scenario(client, mode, "warmup", "benchmark warmup")
                await _scenario(client, mode, "seed", "how do I reset my password")
                rows = []
                rows.append(
                    await _scenario(client, mode, "exact_hit", "how do I reset my password")
                )
                rows.append(
                    await _scenario(client, mode, "near_query", "how do I reset my password please")
                )
                await _scenario(
                    client,
                    mode,
                    "seed",
                    "please tell me the total monthly cost of the 5 gb data plan",
                )
                rows.append(
                    await _scenario(
                        client,
                        mode,
                        "changed_number",
                        "please tell me the total monthly cost of the 50 gb data plan",
                    )
                )
                rows.append(await _scenario(client, mode, "cold_miss", "unique cloud atlas query"))
                rows.append(
                    await _scenario(
                        client, mode, "explicit_bypass", "how do I reset my password", bypass=True
                    )
                )
                rows.append(
                    await _scenario(
                        client,
                        mode,
                        "other_tenant",
                        "how do I reset my password",
                        headers=HEADERS_B,
                    )
                )
                burst = await asyncio.gather(
                    *(
                        _scenario(client, mode, "concurrent_identical", "concurrent unique lookup")
                        for _ in range(8)
                    )
                )
                rows.extend(burst)
                return rows
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


async def run(output: Path) -> Path:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    rows = [*await _measure_mode("exact", output), *await _measure_mode("semantic", output)]
    csv_path = output / "requests.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for mode in ("exact", "semantic"):
        for scenario in sorted({row["scenario"] for row in rows}):
            group = [row for row in rows if row["mode"] == mode and row["scenario"] == scenario]
            if not group:
                continue
            latencies = np.asarray([row["http_complete_ms"] for row in group])
            summary.append(
                {
                    "mode": mode,
                    "scenario": scenario,
                    "n": len(group),
                    "hits": sum(row["cache"] == "HIT" for row in group),
                    "provider_calls": sum(row["mock_provider_invoked"] for row in group),
                    "p50_http_complete_ms": float(np.median(latencies)),
                    "p95_http_complete_ms": float(np.quantile(latencies, 0.95)),
                }
            )
    summary_path = output / "summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)
    manifest = {
        "schema_version": "live-http-redis-mock-v1",
        "environment": "GitHub Actions Redis Stack service expected",
        "redis_url_present": bool(os.environ.get("REDIS_URL")),
        "embedding_backend": "hash (lexical; not the real MiniLM pilot)",
        "provider": "deterministic delayed mock",
        "provider_delay_per_token_s": 0.02,
        "vector_backend": "redisearch",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "outputs": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in ("requests.csv", "summary.csv")
        },
        "limits": (
            "One CI run; no real provider, production traffic, or before/after optimization claim"
        ),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    print(asyncio.run(run(parser.parse_args().output)))
