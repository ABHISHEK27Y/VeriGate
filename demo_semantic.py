"""Semantic demo — shows the REAL embedding model at work (backend = minilm).

    python demo_semantic.py

First run downloads a ~90MB model (once). It demonstrates two things the lexical
hashing embedder could NOT do:

  1. A paraphrase with DIFFERENT WORDS still HITs the cache (true semantic match).
  2. The "Austria" vs "Australia" trap is caught (semantic false-hit prevention).
"""
import logging
import os

os.environ["EMBEDDING_BACKEND"] = "minilm"  # force the real model for this demo

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("verigate.redis").setLevel(logging.WARNING)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
H = {"x-api-key": "demo-key-123"}


def ask(text):
    d = client.post("/v1/chat", json={"prompt": text}, headers=H).json()
    sim = f"{d['similarity']:.3f}" if d.get("similarity") is not None else "  -  "
    thr = f"{d['threshold']:.3f}" if d.get("threshold") is not None else "  -  "
    print(f"  {d['cache']:<6} sim={sim} T={thr} | {text!r}")
    if d.get("note"):
        print(f"         reason: {d['note']}")


print("\nLoading model + warming up (first run downloads ~90MB)...")
ask("warm up the model")

print("\n=== 1) SEMANTIC HIT: different words, same meaning ===")
ask("how do I reset my password")
ask("what is the process to recover my account password")  # no shared keywords -> still HIT

print("\n=== 2) THE AUSTRIA / AUSTRALIA TRAP (semantic false-hit prevention) ===")
ask("what is the capital of Austria")
ask("what is the capital of Australia")  # look-alike, DIFFERENT answer -> must be MISS

print("\n=== 3) A genuinely equivalent country question DOES hit ===")
ask("tell me the capital city of Austria")  # same meaning as #2's first -> HIT

print("\nDone.\n")
