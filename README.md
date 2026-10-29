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
short_description: LLM gateway with an experimental semantic answer cache
---

# VeriGate
### An LLM gateway with a measured, experimental semantic answer cache

> Major Project — B.Tech CSE (AI/DS), IIIT Manipur
> Author: Abhishek Yadav

---

The gateway defaults to exact-prompt cache matching. Set `CACHE_MATCH_MODE=semantic` only
for workloads where approximate reuse is acceptable; NLI does not guarantee correctness.
An additional opt-in `ANSWER_POLICY_ARTIFACT=app/cache/artifacts/answer_policy_v1.json`
routes semantic candidates through an answer-aware ACCEPT / VERIFY / REJECT policy.
VERIFY and REJECT both call the upstream provider. The [controlled comparison](docs/RESULTS_ANSWER_AWARE.md)
reports what that policy did on authored factoid cases, including its latency and limits.
See [production configuration](docs/PRODUCTION_CONFIGURATION.md) and the
[audit report](docs/audit/AUDIT_REPORT.md) for historical findings and release blockers.
New to the stack? Start with the chapter-by-chapter
[VeriGate learning guide](docs/VERIGATE_LEARNING_GUIDE.md) before reading the audit.

## What is this project in one paragraph?

Companies putting Large Language Models (LLMs) into production pay for every single
API call and suffer from high latency. A common fix is a **semantic cache** — if a new
question is "close enough" to a past one, return the stored answer instead of paying
for a new LLM call. A similarity score alone can cause **false cache hits** (returning
the *wrong* stored answer for a look-alike question, e.g. "capital of Austria" vs
"capital of Australia"). Published systems already explore adaptive thresholds and
verification; VeriGate needs a careful comparison before claiming a research advance.

**VeriGate** is an LLM gateway (a proxy in front of LLM providers) with an experimental
semantic answer cache. It computes a query-dependent threshold, applies structural
checks to a retrieved question, and bypasses queries detected as time-sensitive.
These checks **do not verify the cached answer itself**. The hand-curated
query-pair experiment is a smoke test. A newer five-seed evaluation on QQP,
PAWS, and STS-B measures held-out **pair-label proxies** and finds substantial
false pair acceptance; see [generated results](docs/RESULTS_V2.md). Neither
experiment measures real-world answer reuse or cost savings. The mined NQ-Open
factoid study compares reference-answer strings, but some positive labels do not
match the concrete stored answer; see [the label audit](evaluation/results/answer_label_audit.json).
The answer-aware policy is now implemented as an experimental option. Independently
validated answer quality and production operating points remain research goals.
An [experimental learned-policy and replay study](docs/RESULTS_EXPERIMENTAL.md)
also finds weak transfer and has not been enabled in the gateway.
The [current directional replay report](docs/RESULTS_DIRECTIONAL.md) is a local
hash-vector simulation with a validated run manifest, not a provider benchmark.
The [automated judge diagnostic](docs/AUTOMATED_JUDGE_RESULTS.md) runs two pinned
local models on controlled cases and a 350-row queue. FLAN failed to identify any
positive controlled case; the NLI judge made two errors among 15 known cases.
Queue labels are `model_judged` and are not human-reviewed accuracy evidence.

The gateway also provides supporting system features — token-bucket rate
limiting, multi-provider routing with failover, streaming, request-latency metrics,
and an admitted-request budget. Provider token usage and monetary cost are not
accounted for end to end.

---

## Matching modes

| Mode | Behaviour | What it establishes | Main limitation |
|---|---|---|---|
| `exact` (default) | Reuses only an identical prompt within a compatible tenant/model/policy namespace | No approximate-match error | A cached upstream answer can still be stale or wrong |
| `semantic` (opt-in) | Retrieves a nearby question, applies a threshold and optional structural/NLI checks | Can reuse paraphrases in demonstrations | Similar questions and cached answers may still be incompatible; no formal correctness guarantee |

## The academic question

| | |
|---|---|
| **Problem** | How much valid answer reuse is possible while controlling incorrect reuse and verification cost? |
| **Already built** | An exact default, opt-in heuristic semantic policy, query-only verifier, volatility rules, and gateway infrastructure. |
| **Research direction** | Test answer-aware selective verification against fairly tuned baselines. Adaptive thresholds and verification already exist in prior work; see [related work](docs/RESEARCH_BASELINE.md). |
| **Current evidence** | A development smoke fixture; five overlapping splits of public pair-label and NQ reference-string proxies; a simulated chronological replay; and an unreviewed answer queue. None independently establishes response correctness. See [evaluation](evaluation/README.md) and [phase status](docs/PHASE_STATUS.md). |

---

## Repository docs

| Doc | What's inside |
|---|---|
| [`docs/PROJECT_PROPOSAL.md`](docs/PROJECT_PROPOSAL.md) | The formal proposal: problem, motivation, objectives, scope, novelty, deliverables, risks. **Show this to professors first.** |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, components, request lifecycle, data stores, scaling. |
| [`docs/NOVEL_CONTRIBUTION.md`](docs/NOVEL_CONTRIBUTION.md) | Deep dive on the adaptive self-verifying cache — the algorithms, in detail. |
| [`docs/EVALUATION_PLAN.md`](docs/EVALUATION_PLAN.md) | Benchmark design, metrics, baselines, and how results are measured. |
| [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md) | Week-by-week build plan, milestones, definition of done. |
| [`docs/RESULTS_LOG.md`](docs/RESULTS_LOG.md) | Historical exploratory log; read its dated scopes before quoting a result. |
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

🚧 Working prototype + smoke results. Built: streaming gateway, Redis rate limiting, the
opt-in adaptive/structural/staleness-aware semantic cache (real MiniLM embeddings), metrics,
an automated test suite (counts in [the generated check file](evaluation/results/checks.json)
apply to its recorded run), and an **evaluation harness** with candidate-pair figures
(`evaluation/`). See [`QUICKSTART.md`](QUICKSTART.md) to run it and
[`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md) for what's next.

**Evidence limit:** The current CSV reports positive-pair recall and negative-pair
acceptance on a small development fixture. Those numbers are not workload hit rate,
monetary savings, or a general error bound. Run `python -m evaluation.run` to reproduce
the fixture, then `python scripts/export_report_tables.py` to regenerate the report table.
