"""VeriGate gateway — FastAPI app wiring the whole pipeline together.

Pipeline per request (see docs/ARCHITECTURE.md):
  auth -> rate limit -> [staleness -> semantic cache lookup] -> provider+stream -> store -> meter
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__, budget
from .cache import semantic_cache
from .config import settings
from .embeddings import active_backend
from .metrics import BUDGET_EXCEEDED, CACHE, FALSE_HIT_REJECTED, LATENCY, RATE_LIMITED, REQUESTS
from .providers import registry
from .rate_limit import rate_limiter
from .redis_client import redis_backend_name
from .schemas import ChatRequest, ChatResponse

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="VeriGate", version=__version__)


def _auth(api_key: str | None) -> str:
    if not api_key or api_key not in settings.api_key_set:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return api_key


def _tenant(api_key: str) -> str:
    """Stable, opaque tenant id derived from the API key. The cache is partitioned by this,
    so no tenant can ever be served another tenant's cached answer (SECURITY.md #1)."""
    return "t_" + hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _check_rate_limit(api_key: str) -> None:
    allowed, remaining = rate_limiter.allow(api_key)
    if not allowed:
        RATE_LIMITED.inc()
        REQUESTS.labels(outcome="rate_limited").inc()
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def _check_budget(api_key: str) -> None:
    """Charge one provider call against the key's daily budget (cache hits never reach here)."""
    if not budget.check_and_count(api_key):
        BUDGET_EXCEEDED.inc()
        raise HTTPException(status_code=429, detail="daily spend budget exceeded")


_UI_FILE = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/")
@app.get("/ui")
def dashboard():
    """Interactive web dashboard for testing the gateway (served same-origin)."""
    return FileResponse(_UI_FILE)


@app.post("/admin/cache/clear")
def clear_cache(x_api_key: str | None = Header(default=None)):
    """Clear the caller's own tenant cache (requires a valid API key). Used by the dashboard."""
    api_key = _auth(x_api_key)
    semantic_cache.clear(_tenant(api_key))
    return {"status": "cleared"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "redis": redis_backend_name(),
        "embedding_backend": active_backend(),
        "vector_backend": settings.vector_backend,
        "cache_enabled": settings.cache_enabled,
        "providers": [p.name for p in registry.providers()],
    }


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _generate_answer(prompt: str) -> tuple[str, str]:
    """Call the provider (with failover) and assemble the full answer."""
    provider_name, stream = await registry.route_stream(prompt)
    chunks = [chunk async for chunk in stream]
    return provider_name, "".join(chunks).strip()


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    """Non-streaming JSON endpoint — easiest to test/inspect (see X-Cache in the body)."""
    api_key = _auth(x_api_key)
    _check_rate_limit(api_key)
    tenant = _tenant(api_key)

    prompt = req.as_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    t0 = time.perf_counter()
    result = semantic_cache.lookup(prompt, tenant)

    if result.status == "HIT":
        CACHE.labels(result="hit").inc()
        REQUESTS.labels(outcome="hit").inc()
        LATENCY.labels(path="hit").observe(time.perf_counter() - t0)
        return ChatResponse(
            answer=result.answer, cache="HIT", provider="cache",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            threshold=result.threshold, similarity=result.similarity,
            note=result.reason,
        )

    # Track verifier rejections separately (the novelty's key metric)
    if result.reason and result.reason.startswith("verify_rejected"):
        FALSE_HIT_REJECTED.inc()

    _check_budget(api_key)   # only miss/bypass reach a provider — hits are free
    provider_name, answer = await _generate_answer(prompt)

    path = "bypass" if result.status == "BYPASS" else "miss"
    if result.status != "BYPASS":
        semantic_cache.store(prompt, answer, tenant)

    CACHE.labels(result=path).inc()
    REQUESTS.labels(outcome=path).inc()
    LATENCY.labels(path=path).observe(time.perf_counter() - t0)
    return ChatResponse(
        answer=answer, cache=result.status, provider=provider_name,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        threshold=result.threshold, similarity=result.similarity, note=result.reason,
    )


@app.post("/v1/chat/stream")
async def chat_stream(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    """Streaming endpoint (Server-Sent Events). Cache hits stream instantly."""
    api_key = _auth(x_api_key)
    _check_rate_limit(api_key)
    tenant = _tenant(api_key)
    prompt = req.as_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    result = semantic_cache.lookup(prompt, tenant)
    if result.status != "HIT":
        _check_budget(api_key)   # charge the provider call before streaming starts

    async def event_gen():
        if result.status == "HIT":
            CACHE.labels(result="hit").inc()
            yield f"data: {result.answer}\n\n"
            yield "data: [DONE]\n\n"
            return
        if result.reason and result.reason.startswith("verify_rejected"):
            FALSE_HIT_REJECTED.inc()
        provider_name, stream = await registry.route_stream(prompt)
        buf = []
        async for chunk in stream:
            buf.append(chunk)
            yield f"data: {chunk}\n\n"
        if result.status != "BYPASS":
            semantic_cache.store(prompt, "".join(buf).strip(), tenant)
        CACHE.labels(result="bypass" if result.status == "BYPASS" else "miss").inc()
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
