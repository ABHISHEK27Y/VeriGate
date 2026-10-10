"""End-to-end check of the gateway running on the RediSearch backend.

Run with a live Redis Stack:
    REDIS_URL=redis://localhost:6379/0 VECTOR_BACKEND=redisearch \
    EMBEDDING_BACKEND=minilm python -m evaluation.check_redisearch

Verifies a MISS -> HIT (semantic paraphrase) and the Austria/Australia rejection, all
served through the shared Redis HNSW index.
"""

import logging

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("verigate.redis").setLevel(logging.WARNING)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

H = {"x-api-key": "demo-key-123"}


def ask(text, client):
    d = client.post("/v1/chat", json={"prompt": text}, headers=H).json()
    sim = f"{d['similarity']:.3f}" if d.get("similarity") is not None else "  -  "
    print(f"  {d['cache']:<6} sim={sim} | {text!r}  ({d.get('note')})")


with TestClient(app) as client:
    print(f"\nvector_backend = {settings.vector_backend}\n")
    print("=== semantic paraphrase (MISS then HIT via RediSearch) ===")
    ask("how do I reset my password", client)
    ask("what is the process to recover my account password", client)
    print("\n=== Austria/Australia trap (should stay MISS) ===")
    ask("what is the capital of Austria", client)
    ask("what is the capital of Australia", client)
    print()
