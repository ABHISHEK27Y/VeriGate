"""Inspect development misses and input-template sensitivity without changing policy."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from app.cache.answer_policy import AnswerPolicy
from app.cache.verifier import NliVerifier

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evaluation/runs/technical_identity_holdout_20261031_v2"
POLICY = ROOT / "app/cache/artifacts/answer_policy_v1.json"


def rss_bytes() -> int | None:
    """Optional process RSS; the evaluation still runs without psutil."""
    try:
        from psutil import Process  # noqa: PLC0415
    except ImportError:
        return None
    return int(Process().memory_info().rss)


def main() -> None:
    policy = AnswerPolicy.load(POLICY)
    with (RUN / "answer_aware_unchanged/requests.csv").open(encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    selected = [row for row in rows if row["outcome"] == "verifier_false_rejection"]
    verifier = NliVerifier()
    before = rss_bytes()
    started = time.perf_counter()
    verifier.prewarm()
    prewarm_ms = (time.perf_counter() - started) * 1000
    after = rss_bytes()
    results = []
    for row in selected:
        incoming = row["question"]
        stored = row["selected_cached_query"]
        answer = row["selected_cached_answer"]
        assert answer == row["reference_answer"]
        variants = {
            "current": (
                f"The answer to {stored} is {answer}.",
                f"The answer to {incoming} is {answer}.",
            ),
            "compact": (
                f"Question: {stored}\nAnswer: {answer}",
                f"Question: {incoming}\nAnswer: {answer}",
            ),
            "question_only": (stored, incoming),
        }
        measured = {}
        for name, (premise, hypothesis) in variants.items():
            t0 = time.perf_counter()
            assessment = verifier.assess(premise, hypothesis)
            measured[name] = {
                "premise": premise,
                "hypothesis": hypothesis,
                "score": assessment.score,
                "status": assessment.status,
                "tokens": assessment.input_tokens,
                "warm_ms": round((time.perf_counter() - t0) * 1000, 3),
            }
        results.append(
            {
                "id": row["id"],
                "similarity": row["similarity"],
                "historical_reason": row["reason"],
                "accept_at": policy.accept_at,
                "reject_below": policy.reject_below,
                "variants": measured,
            }
        )
    print(
        json.dumps(
            {
                "model": policy.model,
                "revision": policy.revision,
                "prewarm_ms": round(prewarm_ms, 3),
                "rss_before_bytes": before,
                "rss_after_bytes": after,
                "rows": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
