# Deployment & Docker

This explains **what Docker is doing in this project**, how to run the whole stack, and how
to deploy it publicly.

---

## Part 1 — What is Docker doing here? (plain language)

**The problem Docker solves.** Software needs an exact environment: a Python version, system
libraries, other services (Redis). "It works on my machine" happens when those differ between
your laptop and a server. Docker packages an app *with* its environment into a **container** —
a lightweight, isolated box that runs identically everywhere.

**Where Docker shows up in VeriGate — three distinct jobs:**

1. **Running Redis Stack (the only place we use it so far).**
   The RediSearch vector index needs *Redis Stack* (Redis + the search module). Instead of
   installing that on Windows, we run it as a container:
   ```bash
   docker run -d -p 6379:6379 --name redis-stack redis/redis-stack:latest
   ```
   `docker run` = "download this pre-built Redis Stack and start it in a box." `-p 6379:6379`
   forwards the container's port to your machine so the gateway can reach it at
   `localhost:6379`. That single command is why we could verify the RediSearch backend without
   installing or configuring Redis by hand. It keeps running in the background; `docker stop
   redis-stack` / `docker start redis-stack` control it.

2. **Packaging the gateway itself (`Dockerfile`).**
   The `Dockerfile` is a recipe that builds an image of *your* gateway: start from Python
   3.13, install `requirements.txt`, copy the `app/` code, run as a non-root user, and launch
   `uvicorn`. `docker build -t verigate .` produces an image you can run anywhere the same way
   — your machine, a teammate's, or a cloud host. This is what makes deployment reproducible.

3. **Running the whole stack together (`docker-compose.yml`).**
   Real systems are several services at once. `docker-compose.yml` declares two — the gateway
   and Redis Stack — and wires them together (the gateway reaches Redis at the hostname
   `redis`). One command starts both:
   ```bash
   docker compose up --build
   ```
   This is the closest thing to "production on your laptop": the exact services, networked,
   with health checks and a data volume so Redis survives restarts.

**In one line:** Docker is the tool that (a) let us run the special Redis Stack instantly, and
(b) packages the gateway + its dependencies so it runs identically in development and in
production. It is *infrastructure plumbing*, not part of the gateway's logic.

---

## Part 2 — Run the full stack locally

```bash
# free mock LLM (no key)
docker compose up --build

# or with a real model (key from your shell/.env, never baked into the image)
LLM_PROVIDER=gemini GEMINI_API_KEY=your-key docker compose up --build
```
- Gateway: http://localhost:8000  (`/health`, `/docs`, `/metrics`)
- Redis Stack: `localhost:6379`; RedisInsight UI: http://localhost:8001

Stop: `docker compose down` (add `-v` to also delete the Redis volume).

---

## Part 3 — Build & run just the gateway image

```bash
docker build -t verigate .
docker run -p 8000:8000 -e LLM_PROVIDER=mock verigate
```

Notes:
- **Image size finding (measured):** a naive build pulled full **CUDA PyTorch → 10.2 GB**.
  The `Dockerfile` now installs **CPU-only Torch first** (`--index-url .../whl/cpu`), which
  cuts the image to ~1.5 GB. Rebuild to get the slim image. To shrink further, bake the
  embedding model at build time (avoids first-request download).
- Secrets are passed at **run time** via `-e` / compose env, never copied into the image
  (`.env` is excluded by `.dockerignore`).

---

## Part 4 — Deploy to a public host

Any container host works. Easiest first:

| Host | How | Notes |
|---|---|---|
| **Render** | New Web Service → from repo → uses the `Dockerfile`; add a Render Key-Value/Redis or external Redis Cloud | Free tier; set env vars in the dashboard. |
| **Fly.io** | `fly launch` (detects Dockerfile) → `fly deploy`; add Upstash Redis | Global, cheap. |
| **Railway** | Deploy from repo; add a Redis plugin | Simple. |
| **Any VM + Docker** | `docker compose up -d` behind Nginx/Caddy for TLS | Full control. |

**Managed Redis with vector search:** use **Redis Cloud** (free tier includes RediSearch) or
**Upstash**, and point `REDIS_URL` at it with `VECTOR_BACKEND=redisearch`.

**Before you expose it publicly, do the [PRE_DEPLOYMENT_CHECKLIST](PRE_DEPLOYMENT_CHECKLIST.md)
and read [SECURITY](SECURITY.md).** A gateway that forwards to a paid LLM is a spend-and-abuse
target if left open.

---

## Part 5 — Environment variables (deploy-time config)

| Var | Purpose |
|---|---|
| `REDIS_URL` | Redis/Redis Stack connection (blank = in-memory fakeredis, dev only). |
| `VECTOR_BACKEND` | `inproc` (single node) or `redisearch` (shared HNSW). |
| `EMBEDDING_BACKEND` | `minilm` (real) or `hash` (tests). |
| `LLM_PROVIDER` + keys | `mock` / `openai` / `gemini` and the matching API key. |
| `VERIFIER_NLI` | Enable Tier-2 NLI (max-correctness mode). |
| `RATE_LIMIT_*` | Token-bucket capacity / refill. |
| `API_KEYS` | Comma-separated accepted gateway keys. |

Never commit real values — set them in the host's secret store.
