"""Central configuration, loaded from environment / .env file."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Redis: blank => in-memory fakeredis (no server needed).
    redis_url: str = ""

    # Rate limiting (token bucket, per API key)
    rate_limit_capacity: float = 20
    rate_limit_refill_per_sec: float = 5

    # Semantic cache
    cache_enabled: bool = True
    # Base threshold T_base. Calibrated for the "minilm" backend (semantic scores sit
    # lower than lexical ones). The adaptive logic raises it for risky queries.
    cache_similarity_base: float = 0.72

    # Embeddings
    #   "minilm" -> real semantic embeddings via sentence-transformers (default)
    #   "hash"   -> fast dependency-free hashing embedder (lexical only; used in tests)
    embedding_backend: str = "minilm"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 256  # only used by the "hash" backend

    # Vector index backend: "inproc" (in-process NumPy matrix, default) or "redisearch"
    # (shared HNSW index in Redis Stack — requires a Redis Stack server via REDIS_URL).
    vector_backend: str = "inproc"

    # Verifier Tier-2 (NLI). Bidirectional-entailment check for semantic equivalence.
    # OPT-IN: it maximizes correctness (0 false hits) but is conservative and lowers recall,
    # and is largely redundant once the adaptive threshold is on. Enable for correctness-
    # critical deployments (VERIFIER_NLI=true). See docs/RESULTS_LOG.md Phase 4b.
    verifier_nli: bool = False
    nli_model: str = "cross-encoder/nli-deberta-v3-xsmall"
    nli_threshold: float = 0.5

    # Comma-separated list of accepted API keys
    api_keys: str = "demo-key-123"

    # Per-key daily spend cap: max PROVIDER calls per key per day (cache hits are free, so the
    # cache extends the budget). 0 = unlimited. Protects against bill-shock / economic DoS.
    daily_request_budget: int = 0

    # Provider circuit breaker: after N failures in a window, skip the provider for a cooldown.
    breaker_fail_threshold: int = 3
    breaker_window_sec: int = 30
    breaker_cooldown_sec: int = 20

    # Cache entry time-to-live (seconds); 0 = no expiry. Bounds memory + self-heals staleness.
    cache_ttl_sec: int = 0

    # Upstream LLM provider: "mock" (free, default), "openai", or "gemini".
    # Keys come from .env and are never hardcoded/logged. Mock is always kept as failover.
    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_model: str = "gemini-flash-lite-latest"

    # Cost-aware model cascade: send easy queries to the cheap model, escalate hard ones.
    cascade_enabled: bool = False
    cascade_threshold: float = 0.35          # complexity >= this => use the strong model
    openai_strong_model: str = "gpt-4o"      # cheap = openai_model (e.g. gpt-4o-mini)
    gemini_strong_model: str = "gemini-3.5-flash"  # cheap = gemini_model (flash-lite)

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}


settings = Settings()
