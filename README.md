<!-- Hugging Face Spaces reads this YAML block to build the app as a Docker Space.
     It is ignored by GitHub/most viewers. app_port must match the container's port. -->
---
title: VeriGate
emoji: 🧠
colorFrom: green
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
short_description: Adaptive self-verifying semantic cache for LLM gateways
---

# VeriGate
### An Adaptive, Self-Verifying Semantic Cache for Scalable LLM Gateways

> Major Project — B.Tech CSE (AI/DS), IIIT Manipur
> Author: Abhishek Yadav

---

## What is this project in one paragraph?

Companies putting Large Language Models (LLMs) into production pay for every single
API call and suffer from high latency. A common fix is a **semantic cache** — if a new
question is "close enough" to a past one, return the stored answer instead of paying
for a new LLM call. But existing semantic caches use a **single fixed similarity
threshold**, which causes **false cache hits** (returning the *wrong* stored answer for
a look-alike question, e.g. "capital of Austria" vs "capital of Australia").

**VeriGate** is a production-grade **LLM Gateway** (a smart proxy in front of LLM
providers) whose core novel contribution is an **adaptive, self-verifying semantic
cache**: it decides *how strict* to be per query, *verifies* a cached answer actually
fits before returning it, and *refuses to cache* time-sensitive queries. We evaluate it
against a fixed-threshold baseline and show it reduces wrong answers while keeping most
of the cost savings.

The gateway also provides the surrounding production features — token-bucket rate
limiting, multi-provider routing with failover, streaming, and full cost/latency
observability — so the novel cache is demonstrated inside a real, deployable system.

---

## The academic story (gap → method → proof)

| | |
|---|---|
| **Existing systems** | GPTCache, Portkey, LiteLLM, Cloudflare AI Gateway use semantic caching with a *static* similarity threshold. |
| **The gap** | A static threshold trades savings against correctness badly: loose → false hits (wrong answers); strict → low savings. It also blindly caches time-sensitive queries. |
| **Our contribution** | (1) **Adaptive thresholding** per query, (2) a lightweight **verification** step that rejects false hits, (3) **staleness detection** to skip un-cacheable queries. |
| **The proof** | On a purpose-built benchmark of query pairs, VeriGate achieves a better **hit-rate vs. false-hit-rate** trade-off than the static baseline, at comparable cost savings and latency. |

---

## Repository docs

| Doc | What's inside |
|---|---|
| [`docs/PROJECT_PROPOSAL.md`](docs/PROJECT_PROPOSAL.md) | The formal proposal: problem, motivation, objectives, scope, novelty, deliverables, risks. **Show this to professors first.** |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, components, request lifecycle, data stores, scaling. |
| [`docs/NOVEL_CONTRIBUTION.md`](docs/NOVEL_CONTRIBUTION.md) | Deep dive on the adaptive self-verifying cache — the algorithms, in detail. |
| [`docs/EVALUATION_PLAN.md`](docs/EVALUATION_PLAN.md) | Benchmark design, metrics, baselines, and how results are measured. |
| [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md) | Week-by-week build plan, milestones, definition of done. |
| [`docs/RESULTS_LOG.md`](docs/RESULTS_LOG.md) | **Living results log** — phase-by-phase results, charts + what each proves, mapped to report chapters. Append as you go. |
| [`docs/REDISEARCH_UPGRADE.md`](docs/REDISEARCH_UPGRADE.md) | The distributed RediSearch/HNSW vector-index path (production scale) + how to run Redis Stack. |
| [`docs/ARCHITECTURE_PRODUCTION.md`](docs/ARCHITECTURE_PRODUCTION.md) | Target production design — topology, trust boundaries, data model, failure modes. |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model — vulnerabilities (present & future) ranked by severity, with mitigations. |
| [`docs/PRE_DEPLOYMENT_CHECKLIST.md`](docs/PRE_DEPLOYMENT_CHECKLIST.md) | Everything to do before going public, prioritized (blockers marked). |
| [`docs/ENHANCEMENTS.md`](docs/ENHANCEMENTS.md) | Full enhancement roadmap (features, scale, ops, security, research) with value/effort. |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | **What Docker is doing here**, running the full stack, and deploying publicly. |
| [`docs/CODE_WALKTHROUGH.md`](docs/CODE_WALKTHROUGH.md) | **Viva prep** — file-by-file walkthrough, request lifecycle, design decisions, and examiner Q&A. |
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) | Every technology, why it was chosen, and the market skill it demonstrates. |
| [`evaluation/README.md`](evaluation/README.md) | How to run and read the evaluation harness. |

---

## Skills this project demonstrates (for placements)

System design · Redis (as vector store, atomic counter, and state) · caching strategy ·
rate limiting · load balancing & failover · circuit breakers · streaming I/O ·
observability (Prometheus/Grafana) · Docker · cloud deployment · applied LLM engineering
· benchmarking & evaluation.

## Status

🚧 Working system + first results. Built: streaming gateway, Redis rate limiting, the
adaptive/self-verifying/staleness-aware semantic cache (real MiniLM embeddings), metrics,
tests (12 passing), and an **evaluation harness** with the trade-off + ablation figures
(`evaluation/`). See [`QUICKSTART.md`](QUICKSTART.md) to run it and
[`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md) for what's next.

**Headline result:** VeriGate served **0 wrong answers (100% precision)** vs. the
baseline's 46.7% false-hit rate on the benchmark; its trade-off curve dominates the
baseline's. Run `python -m evaluation.run` to reproduce.
