"""Prometheus metrics. Scraped at GET /metrics; visualized in Grafana (Phase 6)."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

REQUESTS = Counter("verigate_requests_total", "Total chat requests", ["outcome"])
CACHE = Counter("verigate_cache_total", "Cache outcomes", ["result"])  # hit/miss/bypass
FALSE_HIT_REJECTED = Counter(
    "verigate_false_hit_rejected_total", "Candidate hits rejected by the verifier",
)
RATE_LIMITED = Counter("verigate_rate_limited_total", "Requests rejected by rate limiter")
BUDGET_EXCEEDED = Counter("verigate_budget_exceeded_total", "Requests rejected by spend budget")
LATENCY = Histogram(
    "verigate_latency_seconds", "End-to-end latency", ["path"],  # path=hit|miss|bypass
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
