"""Semantic demo — shows the REAL embedding model at work (backend = minilm).

    python demo_semantic.py

First run downloads a ~90MB model (once). It demonstrates two things the lexical
hashing embedder could NOT do:

  1. A paraphrase with DIFFERENT WORDS still HITs the cache (true semantic match).
  2. The "Austria" vs "Australia" trap is caught (semantic false-hit prevention).
"""
import logging
import os

from fastapi.testclient import TestClient

from app.main import app

os.environ["EMBEDDING_BACKEND"] = "minilm"  # force the real model for this demo

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("verigate.redis").setLevel(logging.WARNING)

H = {"x-api-key": "demo-key-123"}


def ask(text: str, client: TestClient) -> None:
    d = client.post("/v1/chat", json={"prompt": text}, headers=H).json()
    sim = f"{d['similarity']:.3f}" if d.get("similarity") is not None else "  -  "
    thr = f"{d['threshold']:.3f}" if d.get("threshold") is not None else "  -  "
    print(f"  {d['cache']:<6} sim={sim} T={thr} | {text!r}")
    if d.get("note"):
        print(f"         reason: {d['note']}")


# Use TestClient as context manager to properly initialize lifespan
with TestClient(app, raise_server_exceptions=True) as client:

    print("\nLoading model + warming up (first run downloads ~90MB)...")
    ask("warm up the model", client)

    print("\n=== 1) SEMANTIC HIT: different words, same meaning ===")
    ask("how do I reset my password", client)
    ask(
        "what is the process to recover my account password", client
    )  # no shared keywords -> still HIT

    print("\n=== 2) THE AUSTRIA / AUSTRALIA TRAP (semantic false-hit prevention) ===")
    ask("what is the capital of Austria", client)
    ask("what is the capital of Australia", client)  # look-alike, DIFFERENT answer -> must be MISS

    print("\n=== 3) A genuinely equivalent country question DOES hit ===")
    ask("tell me the capital city of Austria", client)  # same meaning as #2's first -> HIT

    print("\nDone.\n")
