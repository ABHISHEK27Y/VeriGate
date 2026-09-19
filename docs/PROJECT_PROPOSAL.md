# Project Proposal

## VeriGate — An Adaptive, Self-Verifying Semantic Cache for Scalable LLM Gateways

**Program:** B.Tech in Computer Science & Engineering (AI/DS)
**Institute:** Indian Institute of Information Technology, Manipur
**Author:** Abhishek Yadav
**Project type:** Major Project (7th–8th Semester)

---

## 1. Abstract

Large Language Models (LLMs) are now embedded in production software, but every request
to a hosted LLM incurs monetary cost and network latency. **Semantic caching** — reusing
a stored answer when a new query is semantically similar to a previous one — is a proven
technique to reduce both. However, current semantic caches rely on a **single, fixed
similarity threshold** applied uniformly to all queries. This creates an unavoidable
tension: a loose threshold increases the cache hit-rate but returns **incorrect answers**
for superficially-similar-but-different queries ("false cache hits"), while a strict
threshold protects correctness but sacrifices savings. They also cache **time-sensitive**
queries whose answers become stale.

This project proposes **VeriGate**, a horizontally-scalable **LLM Gateway** whose central
contribution is an **adaptive, self-verifying semantic cache**. VeriGate (i) computes a
**per-query adaptive similarity threshold** from query features, (ii) applies a
**lightweight verification step** that confirms a candidate cached answer genuinely
matches the new query before serving it, and (iii) performs **staleness detection** to
avoid caching volatile queries. We implement VeriGate as a complete production gateway
(rate limiting, provider routing/failover, streaming, observability) and **empirically
evaluate** the cache against a fixed-threshold baseline on a purpose-built benchmark,
measuring the hit-rate / false-hit-rate trade-off, cost savings, and latency overhead.

---

## 2. Problem Statement

> Existing LLM semantic caches use a static similarity threshold that cannot simultaneously
> maximize cost savings and preserve answer correctness, and they cache queries whose
> answers are inherently time-sensitive. There is a need for a caching mechanism that adapts
> its strictness per query and verifies cached answers before serving them, without adding
> significant latency.

---

## 3. Motivation

1. **Cost.** Hosted LLM calls are billed per token. Real deployments repeatedly receive
   semantically-equivalent questions ("how do I reset my password?" / "I forgot my
   password, help"). Every repeat is paid again unless cached.
2. **Latency.** An LLM round-trip is typically hundreds of milliseconds to seconds. A cache
   hit answers in single-digit milliseconds.
3. **The correctness risk nobody solves well.** Semantic similarity is not semantic
   equivalence. "Capital of Austria?" and "Capital of Australia?" are embedding-close but
   have different correct answers. A naive cache serves the wrong one — a **silent, hard-to-
   detect failure**. This is the specific weakness VeriGate targets.
4. **Industry relevance.** LLM gateways are a real, growing infrastructure category
   (Portkey, LiteLLM, Cloudflare AI Gateway, Kong AI Gateway). Building one — with a
   genuine improvement to its hardest component — is directly relevant to current industry
   needs and to research on efficient LLM serving.

---

## 4. Objectives

**Primary (novel contribution):**
1. Design and implement an **adaptive similarity thresholding** algorithm that sets cache
   strictness per query from measurable query features.
2. Design and implement a **cache-answer verification** step that rejects false hits before
   they reach the user.
3. Design and implement **staleness/volatility detection** to exclude time-sensitive
   queries from caching.
4. **Evaluate** the above against a fixed-threshold baseline on a labelled benchmark and
   quantify the improvement.

**Secondary (the production platform that hosts the contribution):**
5. Build the LLM Gateway core: authenticated proxy with **streaming** passthrough.
6. Implement **token-bucket rate limiting** backed by Redis (correct across replicas).
7. Implement **multi-provider routing with automatic failover** and a **circuit breaker**.
8. Implement **observability**: cost metering, token accounting, and a Prometheus/Grafana
   dashboard (cache hit-rate, false-hit-rate, p50/p95/p99 latency, cost per key).
9. **Deploy** the system (Docker, cloud) and validate under load.

---

## 5. Scope

**In scope**
- A working, deployable gateway supporting at least two LLM providers.
- The adaptive, self-verifying semantic cache and its evaluation.
- Rate limiting, routing/failover, streaming, observability dashboard.
- A benchmark dataset of query pairs (equivalent vs. non-equivalent) for evaluation.
- A minimal admin dashboard (API keys, live usage/cost).

**Out of scope (explicitly, to keep the project bounded)**
- Training or fine-tuning a foundation LLM from scratch.
- A full commercial billing/subscription system (usage metering only).
- Multi-region/global deployment (single-region, multi-replica is sufficient).
- Fine-grained per-organization RBAC beyond API-key scoping.

---

## 6. Novel Contribution (summary)

The novelty is **not** "an LLM gateway" (those exist). The novelty is the **caching
method inside it**:

1. **Adaptive thresholding** — instead of one global similarity cutoff, VeriGate derives a
   per-query threshold from features such as query length, presence of named entities/
   numbers, and the density of the neighbourhood in vector space. Short, fact-dense queries
   demand tighter matches; long, open-ended queries tolerate looser ones.
2. **Self-verification** — before returning a candidate cached answer, a cheap verifier
   checks that the candidate's *original* query and the new query are truly equivalent
   (entity/number overlap + optional lightweight NLI check), rejecting false hits.
3. **Staleness detection** — a classifier flags volatile queries (temporal keywords,
   real-time intent) and bypasses the cache for them.

A precise, algorithmic description is in [`NOVEL_CONTRIBUTION.md`](NOVEL_CONTRIBUTION.md).

---

## 7. Expected Outcomes / Deliverables

1. **VeriGate system** — source code, Dockerized, deployed with a public demo URL.
2. **The adaptive self-verifying cache** — as a documented, testable module.
3. **Evaluation benchmark** — dataset + scripts, reproducible.
4. **Results** — graphs comparing VeriGate vs. baseline (hit-rate, false-hit-rate, cost,
   latency), written up in the report.
5. **Grafana dashboard** — live operational metrics.
6. **Project report + presentation** following the standard structure.
7. **(Stretch) A short paper draft** suitable for a student/workshop venue.

---

## 8. Success Criteria (how we know it worked)

- VeriGate reduces **false-hit rate by a meaningful margin** (target: ≥50% fewer false
  hits) versus the fixed-threshold baseline **at a comparable overall hit-rate**.
- Verification adds **low latency overhead** on cache hits (target: cache-hit path stays
  an order of magnitude faster than a live LLM call).
- The gateway sustains a defined load (e.g., **≥300 req/s** on modest hardware) with
  correct rate limiting and working failover.
- End-to-end demo: a request is served from cache, a false-hit is *rejected and correctly
  re-answered*, and a provider outage triggers failover — all visible on the dashboard.

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Verification step becomes too slow | Erodes latency benefit | Keep verifier lightweight (entity/number heuristics first, NLI only when needed); measure and cap. |
| Hard to obtain a labelled benchmark | Can't prove novelty | Construct benchmark semi-automatically: paraphrase pairs (positive) + near-miss pairs (hard negatives) from public QA datasets; hand-verify a sample. |
| LLM API costs during development | Budget | Use free tiers + a mock/echo provider for load tests; cache aggressively during dev. |
| Scope creep (too many features) | Miss deadline | Novelty (cache + eval) is prioritized; secondary features are staged and some are optional. |
| Adaptive threshold underperforms | Weak result | Even a negative/mixed result is publishable if the analysis is rigorous; verification alone is expected to reduce false hits. |

---

## 10. High-Level Technology Stack

Backend: **FastAPI (Python)** · Vector + state store: **Redis (Redis Stack, vector search)**
· Embeddings + verification: sentence-embedding model + lightweight NLI/heuristics ·
Providers: **≥2 LLM APIs** (+ a mock provider) · Observability: **Prometheus + Grafana**
· Packaging/deploy: **Docker**, **AWS/Render/Fly.io** · Admin UI: **Next.js + React**.
Full rationale in [`TECH_STACK.md`](TECH_STACK.md).

---

## 11. Timeline (overview)

A ~14-week plan across the major-project period, from a basic proxy to the evaluated,
deployed system. See [`IMPLEMENTATION_ROADMAP.md`](IMPLEMENTATION_ROADMAP.md) for the
week-by-week breakdown, milestones, and definitions of done.

---

## 12. References (to populate during literature survey)

- GPTCache: semantic cache for LLM applications.
- Portkey / LiteLLM / Cloudflare AI Gateway — LLM gateway systems.
- Literature on semantic caching, approximate nearest neighbour (ANN) search, and
  embedding-based retrieval.
- LLM routing / model-cascade literature (related work for the routing component).
- Natural Language Inference (NLI) for semantic equivalence checking.

> *Note:* fill these with proper citations during the literature-survey phase; each
> "existing system" claim in this proposal should map to a citation in the final report.
