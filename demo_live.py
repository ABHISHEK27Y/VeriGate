"""Live demo with a REAL LLM (Gemini/OpenAI) — shows the cache saving real latency + cost.

Prerequisites (in .env):
    LLM_PROVIDER=gemini        (or openai)
    GEMINI_API_KEY=<your key>  (or OPENAI_API_KEY=...)

Run:
    python demo_live.py

You will see the first (MISS) query hit the real model (slow, paid), then repeats and
paraphrases served from the cache in milliseconds ($0) — including a reworded question
matched by meaning.
"""
import logging
import time

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("verigate.redis").setLevel(logging.WARNING)

from app.config import settings  # noqa: E402
from app.providers import registry  # noqa: E402

if settings.llm_provider == "mock" or registry.providers()[0].name == "mock":
    print("\n[!] No real provider active. Set LLM_PROVIDER + an API key in .env "
          "(e.g. LLM_PROVIDER=gemini, GEMINI_API_KEY=...). Using mock otherwise.\n")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
H = {"x-api-key": "demo-key-123"}


def ask(q):
    t0 = time.time()
    d = client.post("/v1/chat", json={"prompt": q}, headers=H).json()
    ms = (time.time() - t0) * 1000
    print(f"  {d['cache']:<5} {d['provider']:<8} {ms:8.0f} ms | {q}")
    print(f"          -> {d['answer'][:90]}")


print(f"\nProvider order: {[p.name for p in registry.providers()]}\n")
print("CACHE PROVIDER  LATENCY   QUERY")
ask("what is a semantic cache")                      # MISS -> real model (slow, paid)
ask("what is a semantic cache")                      # HIT  -> cache (instant, free)
ask("explain what a semantic cache is in one line")  # HIT  -> cache (semantic paraphrase)
ask("what is Redis used for")                        # MISS -> real model again
print("\nThe cache turned slow, paid LLM calls into instant, free hits — including the "
      "reworded question, matched by meaning.\n")
