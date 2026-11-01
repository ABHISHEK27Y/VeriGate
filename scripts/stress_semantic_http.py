"""Frozen 1,000-question NQ-Open controlled-answer HTTP cache evaluation.

Run: python -m scripts.stress_semantic_http build evaluation/runs/NAME
Then: python -m scripts.stress_semantic_http run evaluation/runs/NAME
Each run starts a disposable local gateway with a fresh namespace and tenant.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
import redis.asyncio as redis

from app.identity import tenant_id

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "NQ-open.train.jsonl"
POLICY = ROOT / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
SEED = 90210
FAMILIES = 200
PORT = 8767
HTTP_OK = 200
STARTUP_TIMEOUT_SEC = 360
MIN_TITLE_CHARS = 5
MAX_TITLE_CHARS = 65
MAX_ANSWER_CHARS = 80
REQUESTS = FAMILIES * 5
POLICIES = ("exact", "static", "answer_aware")
CAPACITIES = ("sufficient", "deployment")
SOURCE_URL = "https://github.com/google-research-datasets/natural-questions/tree/master/nq_open"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Cannot write empty rows")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build(output: Path) -> None:  # noqa: PLR0912 - source selection and five fixed transformations
    if output.exists():
        raise FileExistsError(output)
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    rng = random.Random(SEED)
    candidates = []
    seen_answers = set()
    with SOURCE.open(encoding="utf-8") as stream:
        for source_line, line in enumerate(stream, 1):
            source = json.loads(line)
            question = source["question"].strip().rstrip("?")
            if not question.casefold().startswith("who wrote the song "):
                continue
            title = question[len("who wrote the song ") :].strip()
            answers = source["answer"]
            if (
                not title
                or len(title) < MIN_TITLE_CHARS
                or len(title) > MAX_TITLE_CHARS
                or len(answers) != 1
            ):
                continue
            answer = answers[0].strip()
            norm = answer.casefold()
            if not answer or norm in seen_answers or len(answer) > MAX_ANSWER_CHARS:
                continue
            seen_answers.add(norm)
            candidates.append((source_line, title, answer))
    rng.shuffle(candidates)
    if len(candidates) < FAMILIES:
        raise ValueError(f"Only {len(candidates)} eligible source rows")
    chosen = candidates[:FAMILIES]
    rows = []
    answers = {}
    for index, (source_line, title, answer) in enumerate(chosen):
        family = f"song-{index:03d}"
        other_line, other_title, other_answer = chosen[(index + 1) % FAMILIES]
        questions = [
            ("original", f"Who wrote the song {title}?", answer, source_line, "source wording"),
            (
                "paraphrase_1",
                f"Name the writer of the song {title}.",
                answer,
                source_line,
                "authored template",
            ),
            (
                "paraphrase_2",
                f"For the song {title}, who is credited as its writer?",
                answer,
                source_line,
                "authored template",
            ),
            (
                "paraphrase_3",
                f"Identify the person who wrote the song {title}.",
                answer,
                source_line,
                "authored template",
            ),
            (
                "hard_negative",
                f"For the song {other_title}, who wrote it?",
                other_answer,
                other_line,
                "authored entity swap",
            ),
        ]
        for kind, question, reference, evidence_line, transformation in questions:
            if question in answers and answers[question] != reference:
                raise ValueError("Conflicting controlled answers")
            answers[question] = reference
            rows.append(
                {
                    "id": f"{family}:{kind}",
                    "family_id": family,
                    "kind": kind,
                    "question": question,
                    "reference_answer": reference,
                    "family_cached_answer": answer,
                    "family_answer_reusable": kind != "hard_negative",
                    "contrasts_with": f"{family}:original" if kind == "hard_negative" else "",
                    "source_line": evidence_line,
                    "source_url": SOURCE_URL,
                    "evidence": f"NQ-Open train answer at line {evidence_line}",
                    "transformation": transformation,
                    "label_status": "authored_control",
                    "uncertainty": (
                        "NQ short answer may omit co-writers; no independent human review"
                    ),
                }
            )
    assert len(rows) == REQUESTS and len({row["id"] for row in rows}) == REQUESTS
    # Interleave five independently shuffled rounds: same-family gaps span
    # short, medium and long distances without forcing originals to arrive first.
    rng.shuffle(rows)
    for position, row in enumerate(rows, 1):
        row["position"] = position
    positions = defaultdict(list)
    for row in rows:
        positions[row["family_id"]].append(row["position"])
    for row in rows:
        others = [p for p in positions[row["family_id"]] if p < row["position"]]
        row["distance_from_previous_family"] = row["position"] - max(others) if others else ""
    output.mkdir(parents=True)
    write_csv(output / "workload.csv", rows)
    (output / "provider_answers.json").write_text(
        json.dumps(answers, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    freeze = {
        "seed": SEED,
        "families": FAMILIES,
        "requests": len(rows),
        "source": SOURCE_URL,
        "source_license": "CC BY-SA 3.0",
        "source_sha256": digest(SOURCE),
        "policy_sha256": digest(POLICY),
        "policy_artifact": str(POLICY.relative_to(ROOT)),
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "nli_model": "cross-encoder/nli-deberta-v3-xsmall",
        "nli_revision": "a150876415327c80daeff35ca6f68f5ed8cf5c24",
        "static_similarity_base": 0.72,
        "settings": {
            "sufficient": {"cache_ttl_sec": 86400, "max_cache_entries_per_tenant": 1200},
            "deployment": {"cache_ttl_sec": 3600, "max_cache_entries_per_tenant": 256},
        },
        "workload_sha256": digest(output / "workload.csv"),
        "provider_answers_sha256": digest(output / "provider_answers.json"),
        "label_limit": (
            "Authored transformations of NQ references; no independent review. "
            "Co-writers may be missing."
        ),
    }
    (output / "freeze.json").write_text(json.dumps(freeze, indent=2), encoding="utf-8")


async def ready(client: httpx.AsyncClient, process: subprocess.Popen) -> float:
    start = time.perf_counter()
    while time.perf_counter() - start < STARTUP_TIMEOUT_SEC:
        if process.poll() is not None:
            raise RuntimeError("Gateway exited before readiness")
        try:
            response = await client.get("/ready", timeout=2)
            if response.status_code == HTTP_OK and response.json()["status"] == "ok":
                return (time.perf_counter() - start) * 1000
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError("Gateway startup exceeded 360 seconds")


def classify(  # noqa: PLR0911 - mutually exclusive outcome taxonomy
    row: dict, body: dict, status: int, existing: dict[str, str], previously_suitable: bool
) -> str:
    if status != HTTP_OK:
        return "runtime_failure"
    suitable = row["reference_answer"] in existing.values()
    response = body.get("answer")
    if body.get("cache") == "HIT":
        return "correct_hit" if response == row["reference_answer"] else "incorrect_acceptance"
    if body.get("cache") == "BYPASS":
        return "bypass"
    if not suitable:
        return "expiry_or_eviction_miss" if previously_suitable else "cold_miss"
    selected = body.get("selected_cached_query")
    if selected and existing.get(selected) == row["reference_answer"]:
        return "verifier_false_rejection"
    if selected:
        return "correct_rejection_unsuitable_candidate"
    return "retrieval_miss"


async def live_entries(
    client: redis.Redis, key: str, ids_key: str | None
) -> tuple[dict[str, str], str | None]:
    """Read only this evaluation tenant's actual Redis entries before decision."""
    if ids_key is None:
        async for found in client.scan_iter(match=f"cache:v3:*:ids:{tenant_id(key)}"):
            ids_key = found.decode()
            break
        if ids_key is None:
            async for found in client.scan_iter(match=f"cache:v3:*:rs:ids:{tenant_id(key)}"):
                ids_key = found.decode()
                break
    if ids_key is None:
        return {}, None
    members = await client.smembers(ids_key)  # type: ignore[misc]
    if not members:
        return {}, ids_key
    prefix = ids_key.replace(":ids:", ":entry:") + ":"
    async with client.pipeline(transaction=False) as pipe:
        for member in members:
            pipe.hgetall(prefix + member.decode())
        records = await pipe.execute()
    return {
        record[b"query"].decode(): record[b"answer"].decode()
        for record in records
        if record and b"query" in record and b"answer" in record
    }, ids_key


async def run_one(  # noqa: PLR0913, PLR0917 - frozen run inputs
    output: Path,
    policy: str,
    capacity: str,
    rows: list[dict],
    answers: dict[str, str],
    freeze: dict,
) -> dict:
    directory = output / f"{policy}_{capacity}"
    directory.mkdir(exist_ok=False)
    key = f"controlled-stress-{output.name}-{policy}-{capacity}"
    env = dict(os.environ)
    env.update(
        {
            "ENVIRONMENT": "development",
            "HF_HOME": str(ROOT / ".cache" / "huggingface"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "REDIS_URL": "redis://127.0.0.1:6379/0",
            "LLM_PROVIDER": "controlled-eval",
            "EVALUATION_ANSWERS_PATH": str(output / "provider_answers.json"),
            "API_KEYS": key,
            "CACHE_EPOCH": f"stress-{output.name}-{policy}-{capacity}",
            "CACHE_MATCH_MODE": "exact" if policy == "exact" else "semantic",
            "CACHE_POLICY_STATIC": "true" if policy == "static" else "false",
            "ANSWER_POLICY_ARTIFACT": str(POLICY) if policy == "answer_aware" else "",
            "ANSWER_POLICY_PREWARM": "true" if policy == "answer_aware" else "false",
            "EMBEDDING_BACKEND": "minilm",
            "VECTOR_BACKEND": "redisearch",
            "RATE_LIMIT_CAPACITY": "2000",
            "RATE_LIMIT_REFILL_PER_SEC": "2000",
            "DAILY_REQUEST_BUDGET": "0",
            "SHADOW_ENABLED": "false",
            "CACHE_TTL_SEC": str(freeze["settings"][capacity]["cache_ttl_sec"]),
            "MAX_CACHE_ENTRIES_PER_TENANT": str(
                freeze["settings"][capacity]["max_cache_entries_per_tenant"]
            ),
        }
    )
    log = (directory / "gateway.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
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
    observations = []
    previously_generated: set[str] = set()
    redis_client = redis.from_url(env["REDIS_URL"], decode_responses=False)
    ids_key = None
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=180) as client:
            startup_ms = await ready(client, process)
            for index, row in enumerate(rows, 1):
                stored, ids_key = await live_entries(redis_client, key, ids_key)
                previously_suitable = row["reference_answer"] in previously_generated
                suitable = row["reference_answer"] in stored.values()
                start = time.perf_counter()
                try:
                    response = await client.post(
                        "/v1/chat",
                        json={"prompt": row["question"]},
                        headers={"x-api-key": key},
                    )
                    status = response.status_code
                    body = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    status, body = 0, {"note": type(exc).__name__}
                elapsed = (time.perf_counter() - start) * 1000
                outcome = classify(row, body, status, stored, previously_suitable)
                selected = body.get("selected_cached_query")
                record = {
                    **row,
                    "http_status": status,
                    "cache": body.get("cache", "ERROR"),
                    "selected_cached_query": selected or "",
                    "selected_cached_answer": stored.get(selected, "") if selected else "",
                    "actual_answer": body.get("answer", ""),
                    "reason": body.get("note", ""),
                    "similarity": body.get("similarity"),
                    "threshold": body.get("threshold"),
                    "nli_score": body.get("nli_score"),
                    "verifier_invoked": body.get("verifier_invoked"),
                    "provider": body.get("provider", ""),
                    "provider_invoked": status == HTTP_OK and body.get("provider") != "cache",
                    "suitable_answer_present": suitable,
                    "outcome": outcome,
                    "gateway_latency_ms": body.get("latency_ms"),
                    "stage_latency_ms": json.dumps(body.get("stage_latency_ms"), sort_keys=True),
                    "http_latency_ms": round(elapsed, 3),
                }
                observations.append(record)
                if (
                    status == HTTP_OK
                    and body.get("cache") == "MISS"
                    and body.get("provider") == "controlled-eval"
                ):
                    previously_generated.add(body.get("answer", ""))
                # Persist progress after each response for an interrupted run.
                if index % 25 == 0 or index == len(rows):
                    write_csv(directory / "requests.csv", observations)
                    (directory / "progress.json").write_text(
                        json.dumps({"completed": index, "total": len(rows)}), encoding="utf-8"
                    )
    finally:
        await redis_client.aclose()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log.close()
    counts = Counter(row["outcome"] for row in observations)
    opportunities = sum(row["suitable_answer_present"] for row in observations)
    summary = {
        "policy": policy,
        "capacity": capacity,
        "requests": len(rows),
        "completed": sum(row["http_status"] == HTTP_OK for row in observations),
        "failed": counts["runtime_failure"],
        "outcomes": dict(counts),
        "reuse_opportunities": opportunities,
        "successful_reuse_per_opportunity": counts["correct_hit"] / opportunities
        if opportunities
        else None,
        "provider_calls": sum(row["provider_invoked"] for row in observations),
        "startup_ms": round(startup_ms, 3),
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "workload_sha256": freeze["workload_sha256"],
                "policy_sha256": freeze["policy_sha256"],
                "requests_sha256": digest(directory / "requests.csv"),
                "environment": {"python": sys.version, "platform": platform.platform()},
                "config": {
                    key: env[key]
                    for key in (
                        "CACHE_MATCH_MODE",
                        "CACHE_POLICY_STATIC",
                        "ANSWER_POLICY_ARTIFACT",
                        "CACHE_TTL_SEC",
                        "MAX_CACHE_ENTRIES_PER_TENANT",
                        "CACHE_EPOCH",
                        "EMBEDDING_BACKEND",
                        "VECTOR_BACKEND",
                    )
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary


async def run(output: Path) -> None:
    freeze = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    for name, expected in (
        ("workload.csv", freeze["workload_sha256"]),
        ("provider_answers.json", freeze["provider_answers_sha256"]),
        (POLICY, freeze["policy_sha256"]),
    ):
        path = name if isinstance(name, Path) else output / name
        if digest(path) != expected:
            raise ValueError(f"Frozen input changed: {path}")
    with (output / "workload.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    answers = json.loads((output / "provider_answers.json").read_text(encoding="utf-8"))
    for capacity in CAPACITIES:
        for policy in POLICIES:
            name = f"{policy}_{capacity}"
            if (output / name).exists():
                print(f"Skipping existing run {name}", flush=True)
                continue
            print(f"Starting {name}", flush=True)
            summary = await run_one(output, policy, capacity, rows, answers, freeze)
            print(json.dumps(summary), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "run"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.action == "build":
        build(args.output.resolve())
    else:
        asyncio.run(run(args.output.resolve()))


if __name__ == "__main__":
    main()
