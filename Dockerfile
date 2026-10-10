# VeriGate gateway image.
# Multi-purpose: run locally via docker-compose, or deploy to any container host.
FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

# Fast, quiet, no .pyc, unbuffered logs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build tools needed by some ML wheels; removed after install to keep the image slim.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install the pinned CPU runtime, checking every downloaded artifact hash.
COPY requirements-runtime.lock .
RUN pip install --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-runtime.lock

# App code
COPY app ./app

# Run as a non-root user (security hardening)
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Container-level healthcheck hits the gateway's /health endpoint.
# Uses $PORT when the host injects one (e.g. Render), else defaults to 8000 (HF Spaces / local).
# Use 127.0.0.1 since the app binds to 0.0.0.0 inside the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1

# Bind to $PORT if the platform provides one, otherwise 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
