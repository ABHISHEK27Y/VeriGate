# Technology Stack & Rationale

Every technology, *why* it was chosen, and the **market skill it demonstrates**. The last
column is what you can honestly claim in interviews.

---

## Core backend

| Tech | Role in VeriGate | Why / skill demonstrated |
|---|---|---|
| **Python + FastAPI** | Gateway server, async request pipeline, streaming | Async web services, streaming I/O; matches your existing FastAPI experience. |
| **Uvicorn/Gunicorn** | ASGI server, multiple workers | Running a real service, not `python app.py`. |
| **Pydantic** | Request/response validation | Clean, typed API contracts. |

> Optional flex: implement the gateway in **Go** instead for extra infra credibility
> (goroutines suit streaming/proxying). Python is the pragmatic choice given your stack.

## Data / state

| Tech | Role | Why / skill demonstrated |
|---|---|---|
| **Redis (Redis Stack)** | Vector cache index, rate-limit counters, circuit-breaker state, usage counters | Redis used *four* serious ways, incl. **vector search** — strong, current skill. |
| **PostgreSQL** *(optional)* | Durable usage/history for the dashboard | Relational modelling; you already know it. |

## AI / ML components

| Tech | Role | Why / skill demonstrated |
|---|---|---|
| **Sentence-embedding model** (e.g. `all-MiniLM`, `bge-small`) | Query → vector for the cache | Embeddings & vector similarity — core RAG skill. |
| **spaCy / fast NER** | Entity & number extraction for adaptive-T and verification | Practical NLP feature engineering. |
| **Small NLI cross-encoder** (e.g. MiniLM NLI) | Tier-2 semantic-equivalence verification | Applied model use for a precise sub-task. |
| **LLM provider APIs** (≥2, e.g. OpenAI + Gemini/Anthropic) | The upstreams being proxied | Multi-provider integration, streaming APIs. |
| **Mock/echo provider** | Free provider for load tests | Testing infra without burning API budget. |

## Observability

| Tech | Role | Why / skill demonstrated |
|---|---|---|
| **Prometheus** | Metrics scraping (`/metrics`) | Production monitoring vocabulary. |
| **Grafana** | Dashboards for latency/cost/cache | Turning metrics into a story; interview screenshot. |
| **Structured logging** | Traceable request logs | Debuggability at scale. |

## Load testing / evaluation

| Tech | Role | Why / skill demonstrated |
|---|---|---|
| **k6 or Locust** | Throughput/latency load tests | Proving the system under load. |
| **pytest** | Unit/integration tests (rate limiter, verifier, cache) | Testing discipline. |
| **pandas + matplotlib** | Evaluation analysis + figures | Turning raw results into the "money graph". |

## Packaging & deployment

| Tech | Role | Why / skill demonstrated |
|---|---|---|
| **Docker + docker-compose** | Reproducible multi-service local + prod | Containerization — expected baseline skill. |
| **Render / Fly.io / AWS (ECS/EC2)** | Public deployment of the demo | Cloud deploy; put "AWS" on the résumé honestly if you use it. |
| **Nginx / load balancer** | Front multiple replicas | Demonstrates the horizontal-scale story. |

## Frontend (admin dashboard, optional-but-nice)

| Tech | Role | Why / skill demonstrated |
|---|---|---|
| **Next.js + React + Tailwind** | API-key & live usage/cost dashboard | Plays directly to your existing front-end strength. |
| **Recharts** | Usage/cost charts | You already use it — fast to build. |

---

## Minimal viable stack (if you want to keep it lean)

FastAPI · Redis Stack · one embedding model · spaCy · two LLM providers + mock ·
Prometheus + Grafana · Docker · Render/Fly.io. Everything else (Postgres, Next.js
dashboard, Go, third provider) is optional polish.

---

## One-line skill summary for your résumé

> *FastAPI · Redis (vector + atomic ops) · Prometheus/Grafana · Docker · AWS · embeddings/NLI
> · load testing — a horizontally-scalable LLM gateway with a novel adaptive, self-verifying
> semantic cache.*
