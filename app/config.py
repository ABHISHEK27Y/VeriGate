"""Central configuration, loaded from environment / .env file."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_MIN_SALT_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "production"] = "development"

    # Redis: blank => in-memory fakeredis (no server needed).
    redis_url: str = ""

    # Rate limiting (token bucket, per API key)
    rate_limit_capacity: float = Field(default=20, ge=1)
    rate_limit_refill_per_sec: float = Field(default=5, gt=0)

    # Semantic cache
    cache_enabled: bool = True
    cache_match_mode: Literal["exact", "semantic"] = "exact"
    cache_epoch: str = "1"
    max_request_bytes: int = Field(default=65536, gt=0)
    max_concurrent_requests: int = Field(default=64, gt=0)
    request_body_timeout: float = Field(default=10, gt=0)
    max_cached_tenants: int = Field(default=16, gt=0)
    max_cache_entry_bytes: int = Field(default=65536, gt=0)
    # Base threshold T_base. Calibrated for the "minilm" backend (semantic scores sit
    # lower than lexical ones). The adaptive logic raises it for risky queries.
    cache_similarity_base: float = 0.72

    # Embeddings
    #   "minilm" -> real semantic embeddings via sentence-transformers (default)
    #   "hash"   -> fast dependency-free hashing embedder (lexical only; used in tests)
    embedding_backend: str = "minilm"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_revision: str = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    embedding_dim: int = Field(default=256, gt=0, le=4096)  # only used by the "hash" backend

    # Vector index backend: "inproc" (in-process NumPy matrix, default) or "redisearch"
    # (shared HNSW index in Redis Stack — requires a Redis Stack server via REDIS_URL).
    vector_backend: str = "inproc"

    # Verifier Tier-2 (NLI). Bidirectional-entailment check for semantic equivalence.
    # Optional statistical filter; it cannot guarantee semantic equivalence.
    verifier_nli: bool = False
    nli_model: str = "cross-encoder/nli-deberta-v3-xsmall"
    nli_revision: str = "a150876415327c80daeff35ca6f68f5ed8cf5c24"
    nli_threshold: float = 0.5

    # Comma-separated list of accepted API keys
    api_keys: str = "demo-key-123"
    api_key_salt: str = "verigate-development-only"

    # Per-key daily admitted cache misses/bypasses. Not a token or monetary spending cap.
    daily_request_budget: int = Field(default=0, ge=0)

    # Provider circuit breaker: after N failures in a window, skip the provider for a cooldown.
    breaker_fail_threshold: int = 3
    breaker_window_sec: int = 30
    breaker_cooldown_sec: int = 20

    # Cache entry lifetime; finite TTL also expires retired cache namespaces.
    cache_ttl_sec: int = Field(default=3600, gt=0)

    # Finite maximum cache entries per tenant; eviction uses LRU.
    max_cache_entries_per_tenant: int = Field(default=256, gt=0)

    # Metrics endpoint token (for securing /metrics)
    metrics_token: str = "internal-metrics-token"

    # CORS allowed origins (comma-separated). Empty = same-origin only.
    cors_origins: str = ""

    # Provider call timeout (seconds)
    max_response_chars: int = Field(default=1_000_000, gt=0)
    provider_timeout: float = Field(default=30.0, gt=0)

    # Upstream LLM provider: "mock" (free, default), "openai", or "gemini".
    # Mock is used only when explicitly selected; keys come from the environment.
    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_model: str = "gemini-flash-lite-latest"

    # Cost-aware model cascade: send easy queries to the cheap model, escalate hard ones.
    cascade_enabled: bool = False
    cascade_threshold: float = 0.35  # complexity >= this => use the strong model
    openai_strong_model: str = "gpt-4o"  # cheap = openai_model (e.g. gpt-4o-mini)
    gemini_strong_model: str = "gemini-3.5-flash"  # cheap = gemini_model (flash-lite)

    def validate_production(self) -> None:
        if self.environment != "production":
            return
        if not self.redis_url:
            raise ValueError("Production requires shared Redis")
        if not self.api_key_set or "demo-key-123" in self.api_key_set:
            raise ValueError("Production requires non-demo API keys")
        if self.metrics_token == "internal-metrics-token" or not self.metrics_token:
            raise ValueError("Production requires a private metrics token")
        if len(self.api_key_salt) < _MIN_SALT_LENGTH:
            raise ValueError("Production requires API_KEY_SALT of at least 32 characters")
        if "*" in self.cors_origins:
            raise ValueError("Production CORS must use explicit origins")
        if self.llm_provider == "mock":
            raise ValueError("Production requires a real provider")

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}


class RuntimeSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)


settings = Settings()
_runtime: ContextVar[Settings | None] = ContextVar("verigate_config", default=None)


def get_settings() -> Settings:
    """Frozen app configuration in requests; mutable defaults for standalone tools."""
    return _runtime.get() or settings


def snapshot(config: Settings | None = None) -> RuntimeSettings:
    return RuntimeSettings.model_validate((config or settings).model_dump())
