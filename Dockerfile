# VeriGate gateway image.
# Multi-purpose: run locally via docker-compose, or deploy to any container host.
FROM python:3.13-slim

# Fast, quiet, no .pyc, unbuffered logs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build tools needed by some ML wheels; removed after install to keep the image slim.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch FIRST so sentence-transformers doesn't pull the multi-GB CUDA
# build. This shrinks the image dramatically (~10 GB -> ~1.5 GB).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install the rest (torch already satisfied by the CPU wheel above)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app ./app

# Run as a non-root user (security hardening)
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Container-level healthcheck hits the gateway's /health endpoint.
# Uses $PORT when the host injects one (e.g. Render), else defaults to 8000 (HF Spaces / local).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

# Bind to $PORT if the platform provides one, otherwise 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
