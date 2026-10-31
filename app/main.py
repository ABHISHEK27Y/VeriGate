"""VeriGate gateway — FastAPI app wiring the whole pipeline together.

Pipeline per request (see docs/ARCHITECTURE.md):
  auth -> rate limit -> [staleness -> semantic cache lookup] -> provider+stream -> store -> meter
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST

from . import __version__
from .budget import check_and_count as budget_check_and_count
from .cache import redisearch_store as rs
from .cache import storage
from .cache.demo_fixtures import DEMO_API_KEY, FACTS, demo_enabled
from .cache.namespace import POLICY_VERSION
from .cache.semantic_cache import LookupResult, SemanticCache
from .config import Settings, _runtime, get_settings, snapshot
from .embeddings import Embedder
from .identity import key_allowed, tenant_id
from .limits import RequestLimitsMiddleware
from .logging_config import LoggingMiddleware, configure_logging, get_logger
from .metrics import (
    BUDGET_EXCEEDED,
    CACHE,
    CACHE_FAILURES,
    CACHE_WRITES,
    CANDIDATE_DECISION,
    CANDIDATE_VERIFIER_REJECTED,
    LATENCY,
    RATE_LIMITED,
    REQUESTS,
    STAGE_LATENCY,
    render_metrics,
)
from .organization import OrganizationDirectory, Principal, ScopeDecision, content_eligibility
from .providers.base import ProviderEvent
from .providers.registry import ProviderRegistry
from .rate_limit import RateLimiter
from .redis_client import close_redis, create_redis, redis_backend_name
from .schemas import ChatRequest, ChatResponse
from .shadow import ShadowAuditor
from .singleflight import SingleFlight

# Configure structured logging
configure_logging(json_output=True)
log = get_logger("verigate.main")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: PLR0915
    """Application lifespan handler - startup and shutdown."""
    # Startup
    log.info("Starting VeriGate gateway", version=__version__)

    app.state.config = getattr(app.state, "config", snapshot())
    token = _runtime.set(app.state.config)
    redis_client = None
    binary_client = None
    pool_token = None
    try:
        redis_client = create_redis()
        app.state.redis = redis_client
        binary_client = create_redis(binary=True)
        app.state.binary_redis = binary_client
        pool_token = rs.active_client.set(binary_client)
        get_settings().validate_production()
        await app.state.redis.ping()
        if get_settings().environment == "production":
            memory = await app.state.redis.info("memory")
            if int(memory.get("maxmemory", 0)) <= 0:
                raise ValueError("Production Redis requires a finite maxmemory setting")
        app.state.model = Embedder()
        app.state.semantic_cache = SemanticCache(app.state.redis, app.state.model)
        app.state.cache = app.state.semantic_cache
        app.state.index = app.state.cache._index
        app.state.verifier = app.state.cache._policy.verifier
        app.state.organization_directory = OrganizationDirectory(get_settings())
        app.state.provider_registry = (
            ProviderRegistry.from_settings(app.state.redis) if get_settings().api_key_set else None
        )
        app.state.profile_registries = {
            name: ProviderRegistry.from_profile(
                profile, app.state.organization_directory, app.state.redis
            )
            for name, profile in app.state.organization_directory.profiles.items()
            if profile.provider == "mock" or bool(os.environ.get(profile.secret_env))
        }
        app.state.singleflight = SingleFlight()
        app.state.providers = app.state.provider_registry
        app.state.shadow_auditor = (
            ShadowAuditor(app.state.redis, app.state.provider_registry, app.state.config)
            if app.state.provider_registry is not None
            else None
        )
        app.state.rate_limiter = RateLimiter(app.state.redis)
        app.state.budget_check = budget_check_and_count
        if (
            get_settings().embedding_backend == "minilm"
            and get_settings().cache_match_mode == "semantic"
        ):
            await asyncio.to_thread(app.state.model.embed, "warmup")
        if (
            get_settings().cache_match_mode == "semantic"
            and get_settings().answer_policy_artifact
            and get_settings().answer_policy_prewarm
        ):
            await asyncio.to_thread(app.state.semantic_cache._policy.verifier.prewarm)
        if (
            get_settings().vector_backend == "redisearch"
            and get_settings().cache_match_mode == "semantic"
        ):
            vec = await asyncio.to_thread(app.state.model.embed, "dimension probe")
            app.state.embedding_dimension = len(vec)
            await rs.ensure_index(app.state.embedding_dimension)
        yield
    finally:
        log.info("Shutting down VeriGate gateway")
        if getattr(app.state, "shadow_auditor", None) is not None:
            await app.state.shadow_auditor.aclose()
        if getattr(app.state, "provider_registry", None) is not None:
            await app.state.provider_registry.aclose()
        for registry in getattr(app.state, "profile_registries", {}).values():
            await registry.aclose()
        if redis_client is not None:
            await close_redis(redis_client)
        if binary_client is not None:
            await close_redis(binary_client)
        if pool_token is not None:
            rs.active_client.reset(pool_token)
        _runtime.reset(token)


app = FastAPI(
    title="VeriGate",
    version=__version__,
    lifespan=lifespan,
)
app.state.config = snapshot()

# CORS middleware
if app.state.config.cors_origins:
    origins = [o.strip() for o in app.state.config.cors_origins.split(",") if o.strip()]
else:
    origins = []  # same-origin unless explicitly configured

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging middleware (adds request_id, tenant to contextvars)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestLimitsMiddleware, owner=app)


def _auth(api_key: str | None, request: Request | None = None) -> str:
    directory = getattr(request.app.state, "organization_directory", None) if request else None
    try:
        allowed = (
            directory.resolve(api_key) is not None
            if directory
            else key_allowed(api_key, get_settings().api_key_set)
        )
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="identity directory unavailable") from exc
    if not allowed:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    assert api_key is not None
    return api_key


def _tenant(api_key: str) -> str:
    """Stable, opaque tenant id derived from the API key. The cache is partitioned by this,
    so no tenant can ever be served another tenant's cached answer (SECURITY.md #1)."""
    return tenant_id(api_key)


def _admission_identity(principal: Principal, api_key: str) -> str:
    if principal.legacy:
        return api_key
    return (
        f"organization:{principal.organization_id}:"
        f"subject:{principal.subject_id}:application:{principal.application_id}"
    )


def _principal(request: Request, api_key: str | None) -> Principal:
    directory: OrganizationDirectory = request.app.state.organization_directory
    try:
        principal = directory.resolve(api_key)
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="identity directory unavailable") from exc
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return principal


def _still_authorized(request: Request, api_key: str, original: Principal) -> bool:
    """An in-flight generation may finish, but cannot publish after revocation."""
    try:
        return _principal(request, api_key) == original
    except HTTPException:
        return False


def _registry_for(request: Request, principal: Principal) -> ProviderRegistry:
    if principal.legacy:
        if request.app.state.provider_registry is None:
            raise HTTPException(status_code=503, detail="legacy provider unavailable")
        return cast(ProviderRegistry, request.app.state.provider_registry)
    registry = request.app.state.profile_registries.get(principal.provider_profile)
    if registry is None:
        raise HTTPException(status_code=503, detail="organization provider profile unavailable")
    return cast(ProviderRegistry, registry)


def _cache_tenant(  # noqa: PLR0913, PLR0917 - authorization context is explicit
    request: Request,
    prompt: str,
    principal: Principal,
    cache_scope: str | None,
    workspace: str | None,
    registry: ProviderRegistry,
) -> tuple[str, ScopeDecision]:
    directory: OrganizationDirectory = request.app.state.organization_directory
    try:
        decision = directory.scope_decision(principal, cache_scope, workspace, prompt)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    route = registry.intended_route(prompt) if not principal.legacy or registry.cascade else ""
    return directory.scoped_tenant(principal, decision.scope, decision.workspace, route), decision


async def _check_rate_limit(api_key: str, request: Request) -> None:
    try:
        allowed, remaining = await request.app.state.rate_limiter.allow(api_key)
    except Exception as exc:
        log.warning("rate_limit_unavailable", tenant=_tenant(api_key))
        raise HTTPException(status_code=503, detail="admission unavailable") from exc
    if not allowed:
        RATE_LIMITED.inc()
        REQUESTS.labels(outcome="rate_limited").inc()
        log.warning("Rate limit exceeded", tenant=_tenant(api_key))
        raise HTTPException(status_code=429, detail="rate limit exceeded")


async def _check_budget(api_key: str, request: Request) -> None:
    """Charge one admitted miss/bypass; cache hits never reach here."""
    try:
        admitted = await budget_check_and_count(api_key, request.app.state.redis)
    except Exception as exc:
        log.warning("budget_unavailable", tenant=_tenant(api_key))
        raise HTTPException(status_code=503, detail="admission unavailable") from exc
    if not admitted:
        BUDGET_EXCEEDED.inc()
        log.warning("Daily budget exceeded", tenant=_tenant(api_key))
        raise HTTPException(status_code=429, detail="daily request budget exceeded")


async def _cache_lookup(request: Request, prompt: str, tenant: str, bypass: bool) -> LookupResult:
    if bypass:
        return LookupResult(status="BYPASS", reason="requested_bypass")
    try:
        result: LookupResult = await request.app.state.semantic_cache.lookup(prompt, tenant)
    except Exception:
        CACHE_FAILURES.labels(stage="lookup").inc()
        log.warning("cache_lookup_failed", tenant=tenant)
        return LookupResult(status="MISS", reason="cache_unavailable")
    else:
        return result


async def _cache_store(  # noqa: PLR0913 - explicit cache write context
    request: Request,
    prompt: str,
    answer: str,
    tenant: str,
    *,
    metadata: dict[str, str] | None = None,
    deadline: float | None = None,
) -> str:
    started = time.perf_counter()
    try:
        async with asyncio.timeout_at(deadline):
            stored = await request.app.state.semantic_cache.store(
                prompt, answer, tenant, metadata=metadata
            )
    except TimeoutError:
        CACHE_FAILURES.labels(stage="write_timeout").inc()
        CACHE_WRITES.labels(result="failed").inc()
        return "write_timeout"
    except Exception:
        CACHE_FAILURES.labels(stage="write").inc()
        CACHE_WRITES.labels(result="failed").inc()
        log.warning("cache_write_failed", tenant=tenant)
        return "write_failed"
    else:
        outcome = "stored" if stored else "ineligible_or_full"
        CACHE_WRITES.labels(result=outcome).inc()
        return outcome
    finally:
        STAGE_LATENCY.labels(stage="cache_write").observe(time.perf_counter() - started)


async def _lookup_with_overlay(  # noqa: PLR0913, PLR0917 - explicit scope context
    request: Request,
    prompt: str,
    principal: Principal,
    registry: ProviderRegistry,
    tenant: str,
    decision: ScopeDecision,
    bypass: bool,
) -> tuple[LookupResult, str]:
    if decision.eligibility == "no_store":
        return LookupResult(status="BYPASS", reason="no_store_request"), decision.scope
    if not bypass and not principal.legacy and decision.scope == "workspace":
        directory = request.app.state.organization_directory
        private_tenant = directory.scoped_tenant(
            principal, "private", "", registry.intended_route(prompt)
        )
        try:
            overlay = await request.app.state.semantic_cache.lookup_private_overlay(
                prompt,
                private_tenant,
                workspace=decision.workspace,
                application=principal.application_id,
                policy_version=decision.policy_version,
            )
        except Exception:
            CACHE_FAILURES.labels(stage="lookup").inc()
            log.warning("private_overlay_lookup_failed")
        else:
            if overlay is not None:
                return overlay, "private"
    return await _cache_lookup(request, prompt, tenant, bypass), decision.scope


async def _bounded_lookup(  # noqa: PLR0913, PLR0917 - explicit scope context
    request: Request,
    prompt: str,
    principal: Principal,
    registry: ProviderRegistry,
    tenant: str,
    decision: ScopeDecision,
    bypass: bool,
    overall_deadline: float,
) -> tuple[LookupResult, str]:
    loop = asyncio.get_running_loop()
    remaining = min(get_settings().cache_lookup_timeout_sec, overall_deadline - loop.time())
    if remaining <= 0:
        raise HTTPException(status_code=504, detail="request deadline exceeded")
    try:
        async with asyncio.timeout(remaining):
            return await _lookup_with_overlay(
                request, prompt, principal, registry, tenant, decision, bypass
            )
    except TimeoutError:
        CACHE_FAILURES.labels(stage="lookup_timeout").inc()
        if loop.time() >= overall_deadline:
            raise HTTPException(status_code=504, detail="request deadline exceeded") from None
        return LookupResult(status="MISS", reason="cache_lookup_timeout"), decision.scope


def _downgrade_metadata(principal: Principal, decision: ScopeDecision) -> dict[str, str]:
    return {
        "origin_scope": "workspace",
        "origin_workspace": decision.workspace,
        "origin_application": principal.application_id,
        "origin_policy_version": decision.policy_version,
        "response_eligibility": "private_only",
    }


def _count_candidate_decision(result: LookupResult) -> None:
    if result.candidate_trace:
        for candidate in result.candidate_trace:
            action = str(candidate["action"]).lower()
            if action in {"accept", "verify", "reject"}:
                CANDIDATE_DECISION.labels(action=action).inc()
            if action == "reject" and candidate["verifier_status"] == "scored":
                CANDIDATE_VERIFIER_REJECTED.inc()
        return
    reason = result.reason or ""
    if reason.startswith("answer_"):
        action = reason.split(":", 1)[0].removeprefix("answer_")
        if action in {"accept", "verify", "reject"}:
            CANDIDATE_DECISION.labels(action=action).inc()
    if reason.startswith("verify_rejected"):
        CANDIDATE_VERIFIER_REJECTED.inc()


def _check_response_length(length: int) -> None:
    if length > get_settings().max_response_chars:
        raise ResponseTooLargeError


class ResponseTooLargeError(Exception):
    """The configured upstream response limit was exceeded."""


async def _generate_answer(  # noqa: PLR0912 - terminal-event state machine
    prompt: str,
    request: Request,
    registry: ProviderRegistry | None = None,
    *,
    overall_deadline: float,
) -> tuple[str, str, ProviderEvent]:
    """Call the provider (with failover) and assemble the full answer."""
    stream = None
    generation_started = time.perf_counter()
    try:  # noqa: TRY301 - streaming event validation belongs to this stateful loop
        deadline = min(
            overall_deadline,
            asyncio.get_running_loop().time() + get_settings().provider_timeout,
        )
        async with asyncio.timeout_at(deadline):
            route_started = time.perf_counter()
            provider_name, stream = await (
                registry or request.app.state.provider_registry
            ).route_events(prompt)
            STAGE_LATENCY.labels(stage="provider_first_token").observe(
                time.perf_counter() - route_started
            )
            chunks = []
            length = 0
            completion = None
            async for event in stream:
                if event.kind == "complete":
                    if completion is not None:
                        raise RuntimeError("Duplicate provider completion")  # noqa: TRY301
                    completion = event
                elif event.kind == "content":
                    if completion is not None:
                        raise RuntimeError("Content after provider completion")  # noqa: TRY301
                    length += len(event.content)
                    _check_response_length(length)
                    chunks.append(event.content)
            if completion is None or completion.finish_reason != "stop":
                raise RuntimeError("Provider answer did not finish normally")  # noqa: TRY301
    except TimeoutError as exc:
        log.warning("upstream_timeout")
        raise HTTPException(status_code=504, detail="upstream timeout") from exc
    except ResponseTooLargeError as exc:
        log.warning("upstream_response_too_large")
        raise HTTPException(status_code=502, detail="upstream response too large") from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("upstream_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="upstream unavailable") from exc
    finally:
        STAGE_LATENCY.labels(stage="full_generation").observe(
            time.perf_counter() - generation_started
        )
        if stream is not None and hasattr(stream, "aclose"):
            await stream.aclose()
    answer = "".join(chunks).strip()
    if not answer:
        raise HTTPException(status_code=502, detail="empty upstream answer")
    return provider_name, answer, completion


_UI_FILE = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/")
@app.get("/ui")
def dashboard():
    """Interactive web dashboard for testing the gateway (served same-origin)."""
    return FileResponse(_UI_FILE)


@app.post("/admin/cache/clear")
async def clear_cache(request: Request, x_api_key: str | None = Header(default=None)):
    """Clear the caller's own tenant cache (requires a valid API key). Used by the dashboard."""
    api_key = _auth(x_api_key, request)
    principal = _principal(request, api_key)
    if principal.legacy:
        tenant = _tenant(api_key)
        await request.app.state.semantic_cache.clear(tenant)
        for route in request.app.state.provider_registry.cache_scopes():
            await request.app.state.semantic_cache.clear(f"{tenant}:{route}")
    else:
        registry = _registry_for(request, principal)
        # A user-level clear never deletes an authorized workspace's shared answers.
        for route in registry.cache_scopes() or (registry.providers[0].name,):
            tenant = request.app.state.organization_directory.scoped_tenant(
                principal, "private", "", route
            )
            await request.app.state.semantic_cache.clear(tenant)
    return {"status": "cleared"}


@app.get("/admin/cache/occupancy")
async def cache_occupancy(
    request: Request,
    scope: str = "private",
    workspace: str | None = None,
    x_api_key: str | None = Header(default=None),
):
    principal = _principal(request, x_api_key)
    if scope not in {"private", "workspace"}:
        raise HTTPException(status_code=400, detail="unsupported cache scope")
    if scope == "workspace" and (
        principal.legacy
        or not workspace
        or workspace not in principal.workspaces
        or "cache:shared" not in principal.permissions
    ):
        raise HTTPException(status_code=403, detail="Workspace cache access not authorized")
    registry = _registry_for(request, principal)
    routes = registry.cache_scopes() or (registry.providers[0].name,)
    if principal.legacy:
        tenants = [principal.legacy_tenant or ""]
        tenants += [f"{tenants[0]}:{route}" for route in registry.cache_scopes()]
    else:
        tenants = [
            request.app.state.organization_directory.scoped_tenant(
                principal, scope, workspace or "", route
            )
            for route in routes
        ]
    results = []
    for tenant in tenants:
        if (
            get_settings().vector_backend == "redisearch"
            and get_settings().cache_match_mode == "semantic"
        ):
            results.append(await rs.occupancy(tenant))
        else:
            results.append(await storage.occupancy(request.app.state.redis, tenant))
    return {
        "scope": scope,
        "entries": sum(item["entries"] for item in results),
        "redis_entry_bytes": sum(item["redis_entry_bytes"] for item in results),
        "estimated_entries": sum(item["estimated_entries"] for item in results),
        "stale_memberships": sum(item["stale_memberships"] for item in results),
        "earliest_expiry_seconds": min(
            (
                item["earliest_expiry_seconds"]
                for item in results
                if item["earliest_expiry_seconds"]
            ),
            default=0,
        ),
        "evictions": sum(item["evictions"] for item in results),
    }


@app.post("/admin/demo/restore")
async def restore_demo_fixtures(request: Request, x_api_key: str | None = Header(default=None)):
    """Reset only the named local demo tenant, then store labelled factual fixtures."""
    api_key = _auth(x_api_key, request)
    if not demo_enabled(get_settings()) or not hmac.compare_digest(api_key, DEMO_API_KEY):
        raise HTTPException(status_code=404, detail="demo restoration unavailable")
    tenant = _tenant(api_key)
    cache = request.app.state.semantic_cache
    await cache.clear(tenant)
    for question, answer in FACTS:
        await cache.store(question, answer, tenant)
    return {"status": "restored", "tenant": "designated-demo", "fixtures": len(FACTS)}


@app.get("/live")
async def live():
    return {"status": "alive"}


@app.get("/ready")
@app.get("/health")
async def health(request: Request):
    details = await _health_details(request)
    if get_settings().environment == "production":
        return {"status": details["status"]}
    return details


@app.get("/admin/config")
async def config_details(request: Request, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key, request)
    return await _health_details(request)


async def _health_details(request: Request) -> dict:
    try:
        request.app.state.organization_directory._refresh_credentials()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=503, detail="organization configuration requires restart"
        ) from exc
    try:
        await request.app.state.redis.ping()
        if (
            get_settings().vector_backend == "redisearch"
            and get_settings().cache_match_mode == "semantic"
        ):
            await rs.validate_index(request.app.state.embedding_dimension)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc
    missing_profiles = set(request.app.state.organization_directory.profiles) - set(
        request.app.state.profile_registries
    )
    if missing_profiles:
        raise HTTPException(status_code=503, detail="provider profile unavailable")
    answer_verifier = request.app.state.semantic_cache._policy.verifier
    if request.app.state.semantic_cache._answer_policy and (
        answer_verifier.unavailable
        or (get_settings().answer_policy_prewarm and not answer_verifier.prewarmed)
    ):
        raise HTTPException(status_code=503, detail="answer verifier unavailable")
    return {
        "status": "ok",
        "version": __version__,
        "redis": redis_backend_name(),
        "embedding_backend": request.app.state.model.backend,
        "vector_backend": get_settings().vector_backend,
        "cache_enabled": get_settings().cache_enabled,
        "cache_match_mode": get_settings().cache_match_mode,
        "cache_ttl_sec": get_settings().cache_ttl_sec,
        "cache_policy_version": POLICY_VERSION,
        "answer_policy_version": (
            request.app.state.semantic_cache._answer_policy.version[:12]
            if request.app.state.semantic_cache._answer_policy
            else None
        ),
        "answer_policy_prewarm": answer_verifier.prewarmed,
        "answer_verifier_state": (
            "unavailable"
            if answer_verifier.unavailable
            else "loaded"
            if answer_verifier.model is not None
            else "lazy"
        ),
        "answer_verifier_failure": answer_verifier.last_failure_category,
        "demo_restore_available": demo_enabled(get_settings()),
        "organization_demo_available": (
            get_settings().environment == "development"
            and get_settings().llm_provider == "mock"
            and not get_settings().api_key_set
            and Path(get_settings().organization_config_path).name == "organizations-demo.json"
        ),
        "verifier_nli_enabled": get_settings().verifier_nli,
        "provider_health": "configured_not_called",
        "providers": (
            list(request.app.state.provider_registry.cache_scopes())
            if request.app.state.provider_registry and request.app.state.provider_registry.cascade
            else [p.name for p in request.app.state.provider_registry.providers]
            if request.app.state.provider_registry
            else [
                profile.provider
                for profile in request.app.state.organization_directory.profiles.values()
            ]
        ),
    }


async def verify_metrics_token(
    x_metrics_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    if authorization and authorization.startswith("Bearer "):
        x_metrics_token = authorization[7:]
    if (
        not x_metrics_token
        or not get_settings().metrics_token
        or not hmac.compare_digest(x_metrics_token, get_settings().metrics_token)
    ):
        raise HTTPException(status_code=401, detail="invalid metrics token")


@app.get("/metrics", dependencies=[Depends(verify_metrics_token)])
def metrics():
    return PlainTextResponse(render_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(  # noqa: PLR0915 - main gateway request path
    req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None)
):
    """Non-streaming JSON endpoint — easiest to test/inspect (see X-Cache in the body)."""
    overall_deadline = asyncio.get_running_loop().time() + get_settings().request_deadline_sec
    api_key = _auth(x_api_key, request)
    principal = _principal(request, api_key)
    registry = _registry_for(request, principal)
    admission_identity = _admission_identity(principal, api_key)
    await _check_rate_limit(admission_identity, request)
    tenant = principal.legacy_tenant or principal.organization_id

    prompt = req.as_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    t0 = time.perf_counter()
    cache_tenant, scope_decision = _cache_tenant(
        request, prompt, principal, req.cache_scope, req.workspace, registry
    )
    effective_scope = scope_decision.scope
    intended_provider = registry.intended_route(prompt)
    lookup_started = time.perf_counter()
    result, lookup_scope = await _bounded_lookup(
        request,
        prompt,
        principal,
        registry,
        cache_tenant,
        scope_decision,
        req.cache_bypass,
        overall_deadline,
    )
    stage_ms = {"cache_lookup": round((time.perf_counter() - lookup_started) * 1000, 3)}
    _count_candidate_decision(result)

    if result.status == "HIT":
        # Revocation/permission changes during a slow verifier must not serve a hit.
        if _principal(request, api_key) != principal:
            raise HTTPException(status_code=401, detail="credential changed during request")
        if principal.legacy:
            request.app.state.shadow_auditor.maybe_schedule(
                prompt, result.answer or "", tenant, result.cached_query
            )
        CACHE.labels(result="hit").inc()
        REQUESTS.labels(outcome="hit").inc()
        LATENCY.labels(path="hit").observe(time.perf_counter() - t0)
        log.info(
            "cache_hit", tenant=tenant, similarity=result.similarity, threshold=result.threshold
        )
        return ChatResponse(
            answer=result.answer or "",
            cache="HIT",
            provider="cache",
            intended_provider=intended_provider,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            threshold=result.threshold,
            similarity=result.similarity,
            note=result.reason,
            selected_cached_query=result.cached_query
            if get_settings().llm_provider == "controlled-eval"
            else None,
            nli_score=result.nli_score,
            verifier_invoked=result.verifier_invoked,
            stage_latency_ms={**result.stage_latency_ms, **stage_ms},
            organization_id=None if principal.legacy else principal.organization_id,
            subject_id=None if principal.legacy else principal.subject_id,
            cache_scope=lookup_scope,
            lookup_scope=lookup_scope,
            scope_reason=scope_decision.reason,
            scope_policy_version=scope_decision.policy_version,
            storage_eligibility=scope_decision.eligibility,
            request_eligibility=scope_decision.eligibility,
            response_eligibility=content_eligibility(result.answer or ""),
            storage_reason="cache_hit",
            provider_invoked=False,
            provider_profile=None if principal.legacy else principal.provider_profile,
            candidate_count=result.candidate_count,
            selected_rank=result.selected_rank,
            candidate_trace=list(result.candidate_trace),
            storage_outcome="cache_hit",
        )

    admission_started = time.perf_counter()
    if _principal(request, api_key) != principal:
        raise HTTPException(status_code=401, detail="credential changed during request")
    await _check_budget(admission_identity, request)  # only miss/bypass reach provider
    stage_ms["admission"] = round((time.perf_counter() - admission_started) * 1000, 3)
    path = "bypass" if result.status == "BYPASS" else "miss"

    storage_outcome = "not_attempted"
    storage_scope: str | None = None
    storage_reason = "not_attempted"

    async def generate_and_store() -> tuple[str, str, ProviderEvent]:
        nonlocal storage_outcome, storage_scope, storage_reason
        provider_started = time.perf_counter()
        provider_name, answer, completion = await _generate_answer(
            prompt, request, registry, overall_deadline=overall_deadline
        )
        stage_ms["provider"] = round((time.perf_counter() - provider_started) * 1000, 3)
        response_eligibility = content_eligibility(answer)
        if not _still_authorized(request, api_key, principal):
            storage_outcome = "credential_changed_no_store"
            storage_reason = "credential_changed"
        elif provider_name == intended_provider and response_eligibility != "no_store":
            write_tenant = cache_tenant
            storage_scope = effective_scope
            storage_reason = "response_eligible"
            metadata = None
            if not principal.legacy and response_eligibility == "private_only":
                route = registry.intended_route(prompt)
                write_tenant = request.app.state.organization_directory.scoped_tenant(
                    principal, "private", "", route
                )
                storage_scope = "private"
                storage_reason = "response_private_only"
                if effective_scope == "workspace":
                    metadata = _downgrade_metadata(principal, scope_decision)
            write_started = time.perf_counter()
            storage_outcome = await _cache_store(
                request,
                prompt,
                answer,
                write_tenant,
                metadata=metadata,
                deadline=overall_deadline,
            )
            if storage_outcome != "stored":
                storage_scope = None
            stage_ms["cache_write"] = round((time.perf_counter() - write_started) * 1000, 3)
        elif response_eligibility == "no_store":
            storage_outcome = "response_ineligible"
            storage_reason = "response_no_store"
        else:
            storage_outcome = "fallback_not_cached"
            storage_reason = "provider_fallback"
        return provider_name, answer, completion

    if result.status == "BYPASS":
        provider_started = time.perf_counter()
        provider_name, answer, completion = await _generate_answer(
            prompt, request, registry, overall_deadline=overall_deadline
        )
        stage_ms["provider"] = round((time.perf_counter() - provider_started) * 1000, 3)
        joined = False
        storage_outcome = "bypassed"
        storage_reason = "request_bypass"
    else:
        try:
            flight_key = f"{cache_tenant}\x00{principal.subject_id}\x00{prompt}"
            (provider_name, answer, completion), joined = await request.app.state.singleflight.run(
                flight_key,
                generate_and_store,
                min(
                    get_settings().provider_timeout + 2,
                    max(0.001, overall_deadline - asyncio.get_running_loop().time()),
                ),
            )
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="coalesced request timeout") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail="upstream unavailable") from exc

    CACHE.labels(result=path).inc()
    REQUESTS.labels(outcome=path).inc()
    LATENCY.labels(path=path).observe(time.perf_counter() - t0)
    log.info("cache_miss", tenant=tenant, provider=provider_name, path=path)
    return ChatResponse(
        answer=answer,
        cache=result.status,
        provider=provider_name,
        provider_model=completion.model,
        finish_reason=completion.finish_reason,
        provider_usage=None if joined else completion.usage,
        intended_provider=intended_provider,
        fallback_used=provider_name != intended_provider,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        threshold=result.threshold,
        similarity=result.similarity,
        note=f"coalesced:{result.reason}" if joined else result.reason,
        selected_cached_query=result.cached_query
        if get_settings().llm_provider == "controlled-eval"
        else None,
        nli_score=result.nli_score,
        verifier_invoked=result.verifier_invoked,
        stage_latency_ms={**result.stage_latency_ms, **stage_ms},
        organization_id=None if principal.legacy else principal.organization_id,
        subject_id=None if principal.legacy else principal.subject_id,
        cache_scope=lookup_scope,
        lookup_scope=lookup_scope,
        scope_reason=scope_decision.reason,
        scope_policy_version=scope_decision.policy_version,
        storage_eligibility=scope_decision.eligibility,
        request_eligibility=scope_decision.eligibility,
        response_eligibility=content_eligibility(answer),
        storage_scope=None if joined else storage_scope,
        storage_reason="coalesced_follower" if joined else storage_reason,
        provider_invoked=not joined,
        provider_profile=None if principal.legacy else principal.provider_profile,
        candidate_count=result.candidate_count,
        selected_rank=result.selected_rank,
        candidate_trace=list(result.candidate_trace),
        storage_outcome="coalesced" if joined else storage_outcome,
    )


@app.post("/v1/chat/stream")
async def chat_stream(  # noqa: PLR0915, PLR0912 - streaming state machine
    req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None)
):
    """Streaming endpoint (Server-Sent Events). Cache hits stream instantly."""
    started = time.perf_counter()
    overall_deadline = asyncio.get_running_loop().time() + get_settings().request_deadline_sec
    api_key = _auth(x_api_key, request)
    principal = _principal(request, api_key)
    registry = _registry_for(request, principal)
    admission_identity = _admission_identity(principal, api_key)
    await _check_rate_limit(admission_identity, request)
    tenant = principal.legacy_tenant or principal.organization_id
    prompt = req.as_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    cache_tenant, scope_decision = _cache_tenant(
        request, prompt, principal, req.cache_scope, req.workspace, registry
    )
    effective_scope = scope_decision.scope
    intended_provider = registry.intended_route(prompt)
    result, lookup_scope = await _bounded_lookup(
        request,
        prompt,
        principal,
        registry,
        cache_tenant,
        scope_decision,
        req.cache_bypass,
        overall_deadline,
    )
    _count_candidate_decision(result)
    if result.status == "HIT" and _principal(request, api_key) != principal:
        raise HTTPException(status_code=401, detail="credential changed during request")
    if result.status != "HIT":
        if _principal(request, api_key) != principal:
            raise HTTPException(status_code=401, detail="credential changed during request")
        await _check_budget(admission_identity, request)  # charge before streaming starts
        deadline = min(
            overall_deadline,
            asyncio.get_running_loop().time() + get_settings().provider_timeout,
        )
        if asyncio.get_running_loop().time() >= deadline:
            raise HTTPException(status_code=504, detail="request deadline exceeded")
        try:  # noqa: TRY301 - completion must be validated in the streaming state machine
            async with asyncio.timeout_at(deadline):
                route_started = time.perf_counter()
                provider_name, source = await registry.route_events(prompt)
                STAGE_LATENCY.labels(stage="provider_first_token").observe(
                    time.perf_counter() - route_started
                )
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="upstream timeout") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="upstream unavailable") from exc

    async def event_gen():  # noqa: PLR0912, PLR0915 - stream completion state machine
        if result.status == "HIT":
            if principal.legacy:
                request.app.state.shadow_auditor.maybe_schedule(
                    prompt, result.answer or "", tenant, result.cached_query
                )
            CACHE.labels(result="hit").inc()
            REQUESTS.labels(outcome="hit").inc()
            LATENCY.labels(path="hit").observe(time.perf_counter() - started)
            yield f"data: {json.dumps(result.answer)}\n\n"
            yield (
                "event: meta\ndata: "
                + json.dumps(
                    {
                        "lookup_scope": lookup_scope,
                        "request_eligibility": scope_decision.eligibility,
                        "response_eligibility": content_eligibility(result.answer or ""),
                        "storage_scope": None,
                        "storage_reason": "cache_hit",
                        "storage_outcome": "cache_hit",
                        "provider_invoked": False,
                        "provider_usage": None,
                        "candidate_trace": result.candidate_trace,
                    }
                )
                + "\n\n"
            )
            yield "data: [DONE]\n\n"
            return
        buf = []
        length = 0
        completion = None
        generation_started = time.perf_counter()
        try:  # noqa: TRY301 - completion validation is part of this stream state machine
            async with asyncio.timeout_at(deadline):
                async for event in source:
                    if event.kind == "complete":
                        if completion is not None:
                            raise RuntimeError("Duplicate provider completion")  # noqa: TRY301
                        completion = event
                    elif event.kind == "content":
                        if completion is not None:
                            raise RuntimeError("Content after provider completion")  # noqa: TRY301
                        length += len(event.content)
                        _check_response_length(length)
                        buf.append(event.content)
                        yield f"data: {json.dumps(event.content)}\n\n"
                if completion is None or completion.finish_reason != "stop":
                    raise RuntimeError("Provider answer did not finish normally")  # noqa: TRY301
        except Exception as exc:
            log.warning("upstream_stream_failed")
            REQUESTS.labels(outcome="stream_error").inc()
            LATENCY.labels(path="stream_error").observe(time.perf_counter() - started)
            code = (
                "upstream response too large"
                if isinstance(exc, ResponseTooLargeError)
                else "upstream timeout"
                if isinstance(exc, TimeoutError)
                else "upstream unavailable"
            )
            yield f"event: error\ndata: {json.dumps({'error': code})}\n\n"
            return
        finally:
            STAGE_LATENCY.labels(stage="full_generation").observe(
                time.perf_counter() - generation_started
            )
            if hasattr(source, "aclose"):
                await source.aclose()
        answer = "".join(buf).strip()
        if not answer:
            REQUESTS.labels(outcome="stream_error").inc()
            LATENCY.labels(path="stream_error").observe(time.perf_counter() - started)
            yield 'event: error\ndata: {"error":"empty upstream answer"}\n\n'
            return
        response_eligibility = content_eligibility(answer)
        storage_scope = None
        storage_reason = "request_bypass" if result.status == "BYPASS" else "not_attempted"
        storage_outcome = "bypassed" if result.status == "BYPASS" else "not_attempted"
        if result.status != "BYPASS" and provider_name == intended_provider:
            if (
                _still_authorized(request, api_key, principal)
                and response_eligibility != "no_store"
            ):
                write_tenant = cache_tenant
                intended_storage_scope = effective_scope
                storage_reason = "response_eligible"
                metadata = None
                if not principal.legacy and response_eligibility == "private_only":
                    route = registry.intended_route(prompt)
                    write_tenant = request.app.state.organization_directory.scoped_tenant(
                        principal, "private", "", route
                    )
                    intended_storage_scope = "private"
                    storage_reason = "response_private_only"
                    if effective_scope == "workspace":
                        metadata = _downgrade_metadata(principal, scope_decision)
                storage_outcome = await _cache_store(
                    request,
                    prompt,
                    answer,
                    write_tenant,
                    metadata=metadata,
                    deadline=overall_deadline,
                )
                if storage_outcome == "stored":
                    storage_scope = intended_storage_scope
            elif response_eligibility == "no_store":
                storage_reason = "response_no_store"
                storage_outcome = "response_ineligible"
            else:
                storage_reason = "credential_changed"
                storage_outcome = "credential_changed_no_store"
        elif result.status != "BYPASS":
            storage_reason = "provider_fallback"
            storage_outcome = "fallback_not_cached"
        path = "bypass" if result.status == "BYPASS" else "miss"
        CACHE.labels(result=path).inc()
        REQUESTS.labels(outcome=path).inc()
        LATENCY.labels(path=path).observe(time.perf_counter() - started)
        yield (
            "event: meta\ndata: "
            + json.dumps(
                {
                    "lookup_scope": lookup_scope,
                    "request_eligibility": scope_decision.eligibility,
                    "response_eligibility": response_eligibility,
                    "storage_scope": storage_scope,
                    "storage_reason": storage_reason,
                    "storage_outcome": storage_outcome,
                    "provider_invoked": True,
                    "provider_model": completion.model,
                    "finish_reason": completion.finish_reason,
                    "provider_usage": completion.usage,
                    "candidate_trace": result.candidate_trace,
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "X-Provider": "cache" if result.status == "HIT" else provider_name,
            "X-Intended-Provider": intended_provider,
            "X-Cache-Scope": lookup_scope,
            "X-Scope-Reason": scope_decision.reason,
            "X-Scope-Policy-Version": scope_decision.policy_version,
        },
    )


def create_app(config: Settings | None = None) -> FastAPI:
    """Create an isolated gateway; configuration changes require a new application."""
    gateway = FastAPI(title="VeriGate", version=__version__, lifespan=lifespan)
    gateway.state.config = snapshot(config)
    gateway.router.routes.extend(app.router.routes)
    origins = [v.strip() for v in gateway.state.config.cors_origins.split(",") if v.strip()]
    gateway.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    gateway.add_middleware(LoggingMiddleware)
    gateway.add_middleware(RequestLimitsMiddleware, owner=gateway)
    return gateway
