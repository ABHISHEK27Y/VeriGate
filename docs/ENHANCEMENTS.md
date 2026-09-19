# Enhancement Roadmap

Everything VeriGate *could* grow into, grouped by theme. Each item notes **value** and rough
**effort** (S/M/L). Use this to pick report "future work" and to plan beyond the major project.

---

## A. Cache intelligence (the novel core — highest research value)
| Enhancement | Value | Effort |
|---|---|---|
| **Per-tenant cache namespaces** | Correctness + security (blocker for multi-user) | M |
| Learned adaptive threshold (logistic-regression accept-classifier over query features) | Turns heuristic into a trained model; stronger novelty | M |
| Gate Tier-2 NLI to *borderline* similarities only | Keeps NLI's correctness gain without the recall/latency cost | S |
| Learned staleness/volatility classifier (replace keyword rules) | Better recall on time-sensitive queries | M |
| Per-entry TTLs + freshness scoring | Prevents stale answers; enables volatile-with-short-TTL | S |
| Negative caching (remember "no good match") | Avoids repeat expensive lookups | S |
| Cache warming / pre-population from FAQ logs | Higher hit-rate on day one | S |
| Answer-quality feedback loop (thumbs up/down → evict bad entries) | Self-improving cache | M |
| Multi-vector / late-interaction retrieval (ColBERT-style) | Higher retrieval precision | L |

## B. Vector index & scale
| Enhancement | Value | Effort |
|---|---|---|
| RediSearch HNSW tuning (M, efConstruction, efRuntime) + large-corpus benchmark | Real scale numbers for the report | M |
| Quantized / binary vectors | Lower memory, faster | M |
| Sharding / partitioning across Redis nodes | Millions+ of vectors | L |
| Approximate vs exact recall study | Nice evaluation extension | M |

## C. Providers & routing
| Enhancement | Value | Effort |
|---|---|---|
| Circuit breaker + health-based routing | Reliability | M |
| ~~**Cost-aware routing / model cascade**~~ ✅ **DONE** (Phase 15) — ~47% cost cut, no quality loss | Big cost story; research-worthy | M |
| Weighted load balancing across providers | Throughput/resilience | S |
| Mid-stream failover handling | Robust streaming | M |
| More providers (Anthropic, Groq, local vLLM) via the same OpenAI-compat class | Breadth | S |
| Function-calling / tool-use passthrough | Feature completeness | M |

## D. Reliability & operations
| Enhancement | Value | Effort |
|---|---|---|
| ~~Grafana dashboards (from existing Prometheus metrics)~~ ✅ **DONE** (Phase 16) | Observability; report screenshots | S |
| OpenTelemetry tracing | Debuggability at scale | M |
| Graceful shutdown + readiness probe | Production correctness | S |
| Retries with backoff + per-call timeouts (tuned) | Resilience | S |
| Alerting (SLO, cost, memory, provider-down) | Ops maturity | M |

## E. Security & privacy (see SECURITY.md / checklist)
| Enhancement | Value | Effort |
|---|---|---|
| Per-key spend/quota budgets | Prevents bill-shock abuse | M |
| Prompt-injection / jailbreak guard (reuse CyberShield) | Safety; ties to your other project | M |
| PII detection + redaction before caching | Privacy/compliance | M |
| Output moderation hook | Safety | M |
| Secret manager integration + key rotation | Ops security | M |
| `/metrics` auth + TLS + security headers + CORS | Baseline hardening | S |

## F. Product & API
| Enhancement | Value | Effort |
|---|---|---|
| Next.js admin dashboard (keys, live usage/cost, cache browser) | Demo polish; plays to your React strength | M |
| OpenAI-drop-in compatibility (be a transparent proxy for existing SDKs) | Real adoption path | M |
| Multi-turn conversation caching (cache on conversation context) | Feature depth | L |
| Client SDKs / usage examples | Developer experience | S |
| Usage metering + billing hooks (Stripe) | SaaS completeness | L |

## G. Evaluation & research (for the report / a paper)
| Enhancement | Value | Effort |
|---|---|---|
| Expand benchmark (Quora QQP + generated paraphrases, datasheet) | Credible numbers | M |
| Threshold-weight tuning + sensitivity analysis | Rigor | M |
| Ablation with learned components | Stronger claims | M |
| A/B online evaluation (shadow traffic) | Real-world validation | L |
| Write-up as a student/workshop paper | Publication | M |

---

## Suggested next 3 (best value-to-effort for you now)
1. **Per-tenant cache isolation** (security blocker + easy to demo isolation tests).
2. **Grafana dashboard** from the metrics you already emit (great report screenshots, low effort).
3. **Cost-aware model cascade** (a second research-grade contribution with a clean cost graph).
