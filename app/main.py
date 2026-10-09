"""VeriGate gateway — FastAPI app wiring the whole pipeline together.

Pipeline per request (see docs/ARCHITECTURE.md):
  auth -> rate limit -> [staleness -> semantic cache lookup] -> provider+stream -> store -> meter
"""

from __future__ import annotations

import hashlib
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__
from .budget import check_and_count as budget_check_and_count
from .cache.semantic_cache import LookupResult, SemanticCache
from .config import settings
from .embeddings import _resolve_backend, active_backend
from .logging_config import LoggingMiddleware, configure_logging, get_logger
from .metrics import BUDGET_EXCEEDED, CACHE, FALSE_HIT_REJECTED, LATENCY, RATE_LIMITED, REQUESTS
from .providers.registry import ProviderRegistry
from .rate_limit import rate_limiter
from .redis_client import close_redis, redis_backend_name
from .schemas import ChatRequest, ChatResponse

# Configure structured logging
configure_logging(json_output=True)
log = get_logger("verigate.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - startup and shutdown."""
    # Startup
    log.info("Starting VeriGate gateway", version=__version__)

    # Initialize shared state
    app.state.semantic_cache = SemanticCache()
    app.state.provider_registry = ProviderRegistry.from_settings()
    app.state.rate_limiter = rate_limiter
    app.state.budget_check = budget_check_and_count

    # Preload embedding model (for minilm backend)
    if settings.embedding_backend == "minilm":
        log.info("Preloading embedding model...")
        _resolve_backend()  # triggers model load
        log.info("Embedding model loaded")

    yield

    # Shutdown
    log.info("Shutting down VeriGate gateway")
    await close_redis()


app = FastAPI(
    title="VeriGate",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware
if settings.cors_origins:
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
else:
    origins = ["*"]  # dev default - allow all

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging middleware (adds request_id, tenant to contextvars)
app.add_middleware(LoggingMiddleware)


def _auth(api_key: str | None) -> str:
    if not api_key or api_key not in settings.api_key_set:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return api_key


def _tenant(api_key: str) -> str:
    """Stable, opaque tenant id derived from the API key. The cache is partitioned by this,
    so no tenant can ever be served another tenant's cached answer (SECURITY.md #1)."""
    return "t_" + hashlib.sha256(api_key.encode()).hexdigest()[:16]


async def _check_rate_limit(api_key: str) -> None:
    allowed, remaining = await rate_limiter.allow(api_key)
    if not allowed:
        RATE_LIMITED.inc()
        REQUESTS.labels(outcome="rate_limited").inc()
        log.warning("Rate limit exceeded", api_key=api_key[:8] + "...")
        raise HTTPException(status_code=429, detail="rate limit exceeded")


async def _check_budget(api_key: str) -> None:
    """Charge one provider call against the key's daily budget (cache hits never reach here)."""
    if not await budget_check_and_count(api_key):
        BUDGET_EXCEEDED.inc()
        log.warning("Daily budget exceeded", api_key=api_key[:8] + "...")
        raise HTTPException(status_code=429, detail="daily spend budget exceeded")


async def _generate_answer(prompt: str) -> tuple[str, str]:
    """Call the provider (with failover) and assemble the full answer."""
    provider_name, stream = await app.state.provider_registry.route_stream(prompt)
    chunks = [chunk async for chunk in stream]
    return provider_name, "".join(chunks).strip()


_UI_FILE = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/")
@app.get("/ui")
def dashboard():
    """Interactive web dashboard for testing the gateway (served same-origin)."""
    return FileResponse(_UI_FILE)


@app.post("/admin/cache/clear")
async def clear_cache(x_api_key: str | None = Header(default=None)):
    """Clear the caller's own tenant cache (requires a valid API key). Used by the dashboard."""
    api_key = _auth(x_api_key)
    await app.state.semantic_cache.clear(_tenant(api_key))
    return {"status": "cleared"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": __version__,
        "redis": redis_backend_name(),
        "embedding_backend": active_backend(),
        "vector_backend": settings.vector_backend,
        "cache_enabled": settings.cache_enabled,
        "providers": [p.name for p in app.state.provider_registry.providers],
    }


async def verify_metrics_token(x_metrics_token: str | None = Header(default=None)):
    if x_metrics_token != settings.metrics_token:
        raise HTTPException(status_code=401, detail="invalid metrics token")


@app.get("/metrics", dependencies=[Depends(verify_metrics_token)])
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    """Non-streaming JSON endpoint — easiest to test/inspect (see X-Cache in the body)."""
    api_key = _auth(x_api_key)
    await _check_rate_limit(api_key)
    tenant = _tenant(api_key)

    prompt = req.as_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    t0 = time.perf_counter()
    result: LookupResult = await app.state.semantic_cache.lookup(prompt, tenant)

    if result.status == "HIT":
        CACHE.labels(result="hit").inc()
        REQUESTS.labels(outcome="hit").inc()
        LATENCY.labels(path="hit").observe(time.perf_counter() - t0)
        log.info(
            "cache_hit", tenant=tenant, similarity=result.similarity, threshold=result.threshold
        )
        return ChatResponse(
            answer=result.answer,
            cache="HIT",
            provider="cache",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            threshold=result.threshold,
            similarity=result.similarity,
            note=result.reason,
        )

    # Track verifier rejections separately (the novelty's key metric)
    if result.reason and result.reason.startswith("verify_rejected"):
        FALSE_HIT_REJECTED.inc()

    await _check_budget(api_key)  # only miss/bypass reach a provider — hits are free
    provider_name, answer = await _generate_answer(prompt)

    path = "bypass" if result.status == "BYPASS" else "miss"
    if result.status != "BYPASS":
        await app.state.semantic_cache.store(prompt, answer, tenant)

    CACHE.labels(result=path).inc()
    REQUESTS.labels(outcome=path).inc()
    LATENCY.labels(path=path).observe(time.perf_counter() - t0)
    log.info("cache_miss", tenant=tenant, provider=provider_name, path=path)
    return ChatResponse(
        answer=answer,
        cache=result.status,
        provider=provider_name,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        threshold=result.threshold,
        similarity=result.similarity,
        note=result.reason,
    )


@app.post("/v1/chat/stream")
async def chat_stream(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    """Streaming endpoint (Server-Sent Events). Cache hits stream instantly."""
    api_key = _auth(x_api_key)
    await _check_rate_limit(api_key)
    tenant = _tenant(api_key)
    prompt = req.as_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    result: LookupResult = await app.state.semantic_cache.lookup(prompt, tenant)
    if result.status != "HIT":
        await _check_budget(api_key)  # charge the provider call before streaming starts

    async def event_gen():
        if result.status == "HIT":
            CACHE.labels(result="hit").inc()
            yield f"data: {result.answer}\n\n"
            yield "data: [DONE]\n\n"
            return
        if result.reason and result.reason.startswith("verify_rejected"):
            FALSE_HIT_REJECTED.inc()
        provider_name, stream = await app.state.provider_registry.route_stream(prompt)
        buf = []
        async for chunk in stream:
            buf.append(chunk)
            yield f"data: {chunk}\n\n"
        if result.status != "BYPASS":
            await app.state.semantic_cache.store(prompt, "".join(buf).strip(), tenant)
        CACHE.labels(result="bypass" if result.status == "BYPASS" else "miss").inc()
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
