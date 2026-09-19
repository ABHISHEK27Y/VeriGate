"""Human-friendly demo: run the gateway in-process and print what happens.

    python demo.py

No server, no Redis install needed. It shows: cache MISS -> HIT, a false-hit being
REJECTED by the verifier, a volatile query BYPASSING the cache, and rate limiting.
"""
import logging

from fastapi.testclient import TestClient

# Keep the demo output readable (hide per-request HTTP/redis INFO logs).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("verigate.redis").setLevel(logging.WARNING)

from app.main import app

client = TestClient(app)
H = {"x-api-key": "demo-key-123"}


def ask(text):
    r = client.post("/v1/chat", json={"prompt": text}, headers=H)
    if r.status_code == 429:
        print(f"  429 RATE LIMITED   | {text!r}")
        return
    d = r.json()
    sim = f"{d['similarity']:.3f}" if d.get("similarity") is not None else "  -  "
    thr = f"{d['threshold']:.3f}" if d.get("threshold") is not None else "  -  "
    print(f"  {d['cache']:<6} sim={sim} T={thr} | {text!r}\n         -> {d['answer'][:60]}")


print("\n=== 1) MISS then HIT (paraphrase) ===")
ask("how do I reset my password")
ask("how do I reset my password please")

print("\n=== 2) FALSE HIT REJECTED (near-identical wording, different number) ===")
ask("please tell me the total monthly cost of the 5 gb data plan for a new user")
ask("please tell me the total monthly cost of the 50 gb data plan for a new user")  # MISS, not the 5gb answer

print("\n=== 3) VOLATILE query BYPASSES cache ===")
ask("what is the weather today")
ask("what is the weather today")

print("\n=== 4) RATE LIMIT (burst of requests) ===")
for i in range(25):
    ask(f"distinct question {i}")

print("\nDone. Check GET /metrics when running as a server for the counters.\n")
