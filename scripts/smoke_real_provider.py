"""Bounded real-provider gateway smoke test; preflight never makes paid calls.

Execution needs a provider key, disposable Redis, and an externally enforced
account spending cap. At most three new prompts are sent to one configured model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MAX_PROVIDER_CALLS = 3
MAX_OUTPUT_CHARS = 2048
MAX_TIMEOUT_SEC = 30.0


def prerequisites(settings: Settings, environment: dict[str, str]) -> list[str]:
    missing = []
    if not settings.redis_url:
        missing.append("REDIS_URL for a disposable Redis instance")
    if not settings.answer_policy_artifact:
        missing.append("ANSWER_POLICY_ARTIFACT for answer-aware semantic mode")
    if settings.embedding_backend != "minilm" or settings.vector_backend != "redisearch":
        missing.append("EMBEDDING_BACKEND=minilm and VECTOR_BACKEND=redisearch")
    if settings.llm_provider not in {"openai", "gemini"}:
        missing.append("LLM_PROVIDER=openai or gemini")
    if settings.llm_provider == "openai" and not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if settings.llm_provider == "gemini" and not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not settings.api_keys or settings.api_keys == "demo-key-123":
        missing.append("non-demo API_KEYS")
    if environment.get("VERIGATE_SMOKE_ACCOUNT_HARD_CAP_CONFIRMED") != "1":
        missing.append("VERIGATE_SMOKE_ACCOUNT_HARD_CAP_CONFIRMED=1")
    try:
        approved = float(environment.get("VERIGATE_SMOKE_APPROVED_MAX_USD", ""))
    except ValueError:
        approved = 0.0
    if not math.isfinite(approved) or approved <= 0:
        missing.append("VERIGATE_SMOKE_APPROVED_MAX_USD > 0")
    return missing


def run(output: Path, settings: Settings) -> dict:
    if output.exists():
        raise FileExistsError(output)
    missing = prerequisites(settings, dict(os.environ))
    if missing:
        raise RuntimeError("Smoke prerequisites missing: " + ", ".join(missing))
    # One target only; no paid cascade or fallback attempts. Semantic reuse is
    # explicitly tested while shadow stays off and the three-call ceiling is inspectable.
    bounded = settings.model_copy(
        update={
            "cache_match_mode": "semantic",
            "cascade_enabled": False,
            "shadow_enabled": False,
            "provider_timeout": min(settings.provider_timeout, MAX_TIMEOUT_SEC),
            "max_response_chars": min(settings.max_response_chars, MAX_OUTPUT_CHARS),
            "cache_epoch": f"real-provider-smoke-{uuid.uuid4().hex}",
        }
    )
    api_key = bounded.api_keys.split(",")[0].strip()
    headers = {"x-api-key": api_key}
    nonce = uuid.uuid4().hex[:12]
    prompt = f"Reply with one short sentence about a blue bicycle. Test ID {nonce}."
    paraphrase = f"Give one short sentence about a blue bicycle. Test ID {nonce}."
    stream_prompt = f"Reply with one short sentence about a green umbrella. Test ID {nonce}."
    started = time.perf_counter()
    with TestClient(create_app(bounded)) as client:
        first = client.post("/v1/chat", json={"prompt": prompt}, headers=headers)
        first.raise_for_status()
        first_body = first.json()
        second = client.post("/v1/chat", json={"prompt": prompt}, headers=headers)
        second.raise_for_status()
        second_body = second.json()
        similar = client.post("/v1/chat", json={"prompt": paraphrase}, headers=headers)
        similar.raise_for_status()
        similar_body = similar.json()
        streamed = client.post("/v1/chat/stream", json={"prompt": stream_prompt}, headers=headers)
        streamed.raise_for_status()
        stream_hit = client.post("/v1/chat/stream", json={"prompt": stream_prompt}, headers=headers)
        stream_hit.raise_for_status()
        cleared = client.post("/admin/cache/clear", headers=headers)
        cleared.raise_for_status()
    checks = {
        "json_generated": first_body["cache"] == "MISS" and bool(first_body["answer"].strip()),
        "json_cached": second_body["cache"] == "HIT"
        and second_body["answer"] == first_body["answer"],
        "paraphrase_decided": (
            similar_body["cache"] == "HIT"
            and similar_body["answer"] == first_body["answer"]
            and similar_body["note"].startswith("answer_accept:")
        )
        or (
            similar_body["cache"] == "MISS"
            and similar_body["provider"] == bounded.llm_provider
            and similar_body["note"].startswith(("answer_verify:", "answer_reject:"))
        ),
        "stream_completed": "data: [DONE]" in streamed.text and "event: error" not in streamed.text,
        "stream_cached": stream_hit.headers.get("x-provider") == "cache"
        and "data: [DONE]" in stream_hit.text,
        "cache_cleanup": cleared.json().get("status") == "cleared",
        "connection_cleanup": True,  # TestClient lifespan exited without exception.
    }
    result = {
        "schema_version": "real-provider-smoke-v1",
        "provider": bounded.llm_provider,
        "model": bounded.openai_model if bounded.llm_provider == "openai" else bounded.gemini_model,
        "max_provider_calls": MAX_PROVIDER_CALLS,
        "approved_max_usd": float(os.environ["VERIGATE_SMOKE_APPROVED_MAX_USD"]),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "checks": checks,
        "paraphrase_decision": {
            "cache": similar_body["cache"],
            "reason": similar_body["note"],
            "similarity": similar_body["similarity"],
        },
        "answers_sha256": [
            hashlib.sha256(first_body["answer"].encode()).hexdigest(),
            hashlib.sha256(streamed.text.encode()).hexdigest(),
        ],
        "limitations": (
            "External account cap controls dollars; this harness caps requests, not billed tokens."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not all(checks.values()):
        raise AssertionError("Real provider smoke failed; inspect saved result")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute", action="store_true", help="allow up to three real provider calls"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = Settings()
    missing = prerequisites(config, dict(os.environ))
    if not args.execute:
        print(json.dumps({"ready": not missing, "missing": missing, "paid_calls": 0}, indent=2))
    else:
        if args.output is None:
            parser.error("--output is required with --execute")
        print(json.dumps(run(args.output, config), indent=2))
