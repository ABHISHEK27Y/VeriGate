"""Exercise two independent gateway processes against one Redis Stack service."""

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

ROOT = Path(__file__).resolve().parents[1]
PORTS = (8767, 8768)
API_KEYS = ("tenant-a", "tenant-b", "rate-key", "budget-key", "dup-0", "dup-1", "dup-2")
HTTP_OK = 200
TRIALS = 3
STARTUP_TIMEOUT_SEC = 60
RATE_LIMITED = 429


async def _ready(client: httpx.AsyncClient, process: subprocess.Popen) -> None:
    started = time.perf_counter()
    while time.perf_counter() - started < STARTUP_TIMEOUT_SEC:
        if process.poll() is not None:
            raise RuntimeError("Worker exited before readiness")
        try:
            if (await client.get("/health", timeout=2)).status_code == HTTP_OK:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.2)
    raise TimeoutError("Worker startup timeout")


async def _call(client: httpx.AsyncClient, worker: int, case: str, key: str, prompt: str) -> dict:
    started = time.perf_counter()
    response = await client.post(
        "/v1/chat", json={"prompt": prompt}, headers={"x-api-key": key}, timeout=30
    )
    body = response.json()
    note = body.get("note", "")
    return {
        "case": case,
        "worker": worker,
        "status": response.status_code,
        "cache": body.get("cache", ""),
        "note": note,
        "provider_call": response.status_code == HTTP_OK
        and body.get("provider") != "cache"
        and not note.startswith("coalesced:"),
        "http_complete_ms": round((time.perf_counter() - started) * 1000, 3),
    }


async def run(output: Path) -> Path:  # noqa: PLR0912, PLR0915 - one controlled test
    if not os.environ.get("REDIS_URL"):
        raise ValueError("REDIS_URL must point to disposable Redis Stack")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    env = dict(os.environ)
    env.update(
        {
            "CACHE_MATCH_MODE": "exact",
            "EMBEDDING_BACKEND": "hash",
            "VECTOR_BACKEND": "redisearch",
            "LLM_PROVIDER": "mock",
            "API_KEYS": ",".join(API_KEYS),
            "RATE_LIMIT_CAPACITY": "6",
            "RATE_LIMIT_REFILL_PER_SEC": "0.0001",
            "DAILY_REQUEST_BUDGET": "5",
            "CACHE_EPOCH": f"two-workers-{output.name}",
            "SHADOW_ENABLED": "false",
        }
    )
    processes = []
    logs = []
    rows: list[dict] = []
    try:
        for port in PORTS:
            log = (output / f"worker_{port}.log").open("w", encoding="utf-8")
            logs.append(log)
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
            processes.append(process)
        async with (
            httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORTS[0]}") as a,
            httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORTS[1]}") as b,
        ):
            await asyncio.gather(_ready(a, processes[0]), _ready(b, processes[1]))
            rows.append(await _call(a, 1, "seed", "tenant-a", "shared secret question"))
            rows.append(await _call(b, 2, "other_tenant", "tenant-b", "shared secret question"))
            rows.append(await _call(b, 2, "same_tenant", "tenant-a", "shared secret question"))
            cleared = await a.post(
                "/admin/cache/clear", headers={"x-api-key": "tenant-a"}, timeout=10
            )
            if cleared.status_code != HTTP_OK:
                raise AssertionError("Tenant invalidation failed")
            rows.append(
                await _call(b, 2, "after_invalidation", "tenant-a", "shared secret question")
            )

            # A cache hit does not consume daily budget, but all requests consume
            # the shared rate limiter. Ports alternate on the same API key.
            rows.append(await _call(a, 1, "rate_seed", "rate-key", "rate limit seed"))
            for index in range(6):
                client, worker = (a, 1) if index % 2 == 0 else (b, 2)
                rows.append(await _call(client, worker, "rate", "rate-key", "rate limit seed"))
            for index in range(6):
                client, worker = (a, 1) if index % 2 == 0 else (b, 2)
                rows.append(
                    await _call(client, worker, "budget", "budget-key", f"budget miss {index}")
                )
            for trial in range(TRIALS):
                key = f"dup-{trial}"
                prompt = f"cold duplicate across workers {trial}"
                rows.extend(
                    await asyncio.gather(
                        _call(a, 1, f"duplicate_{trial}", key, prompt),
                        _call(b, 2, f"duplicate_{trial}", key, prompt),
                    )
                )
    finally:
        for process in processes:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        for log in logs:
            log.close()

    with (output / "requests.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "same_tenant_hit": next(row["cache"] for row in rows if row["case"] == "same_tenant"),
        "other_tenant_miss": next(row["cache"] for row in rows if row["case"] == "other_tenant"),
        "invalidation_miss": next(
            row["cache"] for row in rows if row["case"] == "after_invalidation"
        ),
        "rate_denied_status": [row["status"] for row in rows if row["case"] == "rate"][-1],
        "budget_denied_status": [row["status"] for row in rows if row["case"] == "budget"][-1],
        "duplicate_trials": TRIALS,
        "duplicate_provider_calls": [
            sum(row["provider_call"] for row in rows if row["case"] == f"duplicate_{trial}")
            for trial in range(TRIALS)
        ],
        "errors": sum(row["status"] not in {HTTP_OK, RATE_LIMITED} for row in rows),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "two-worker-redis-v1",
        "workers": 2,
        "cache_mode": "exact",
        "provider": "delayed deterministic mock",
        "redis_url_present": True,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "outputs": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in ("requests.csv", "summary.json")
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if (
        summary["same_tenant_hit"] != "HIT"
        or summary["other_tenant_miss"] != "MISS"
        or summary["invalidation_miss"] != "MISS"
        or summary["rate_denied_status"] != RATE_LIMITED
        or summary["budget_denied_status"] != RATE_LIMITED
        or summary["errors"]
    ):
        raise AssertionError("Two-worker Redis controls failed; inspect saved rows")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    print(asyncio.run(run(parser.parse_args().output)))
