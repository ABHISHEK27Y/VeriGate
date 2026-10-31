"""Compare frozen NLI inputs on fixed MiniLM candidates; no provider calls."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import time
from collections import Counter
from pathlib import Path

import numpy as np

from app.cache.answer_policy import AnswerPolicy
from app.cache.verifier import NliAssessment, NliVerifier
from app.embeddings import Embedder

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evaluation/runs/technical_nli_holdout_20261031_v1"
POLICY = ROOT / "app/cache/artifacts/answer_policy_v1.json"


def rss_bytes() -> int | None:
    """Optional process RSS; the comparison still runs without psutil."""
    try:
        from psutil import Process  # noqa: PLC0415
    except ImportError:
        return None
    return int(Process().memory_info().rss)


class QuestionOnlyInput(NliVerifier):
    """Evaluation adapter: same model, replace only the NLI pair text."""

    def __init__(self, model: NliVerifier, answer: str):
        self.verifier = model
        self.answer = answer

    def assess(self, premise: str, hypothesis: str) -> NliAssessment:
        suffix = f" is {self.answer}."
        if not premise.startswith("The answer to ") or not premise.endswith(suffix):
            raise ValueError("Unexpected premise construction")
        if not hypothesis.startswith("The answer to ") or not hypothesis.endswith(suffix):
            raise ValueError("Unexpected hypothesis construction")
        stored = premise[len("The answer to ") : -len(suffix)]
        incoming = hypothesis[len("The answer to ") : -len(suffix)]
        return self.verifier.assess(stored, incoming)


def main(output_dir: Path) -> None:
    freeze = json.loads((RUN / "freeze.json").read_text(encoding="utf-8"))
    workload = RUN / "workload.csv"
    if hashlib.sha256(workload.read_bytes()).hexdigest() != freeze["workload_sha256"]:
        raise ValueError("Frozen workload changed")
    if (output_dir / "decisions.csv").exists() or (output_dir / "summary.json").exists():
        raise FileExistsError("Evaluation output already exists")
    with workload.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != freeze["rows"] or len({row["family"] for row in rows}) != freeze["families"]:
        raise ValueError("Frozen row/family count changed")
    policy = AnswerPolicy.load(POLICY)
    if (policy.accept_at, policy.reject_below, policy.min_similarity) != (
        freeze["accept_at"],
        freeze["reject_below"],
        freeze["min_similarity"],
    ):
        raise ValueError("Policy thresholds changed")

    rss_initial = rss_bytes()
    started = time.perf_counter()
    embedder = Embedder()
    vectors = {
        query: embedder.embed(query)
        for query in {text for row in rows for text in (row["stored_query"], row["incoming_query"])}
    }
    embedding_load_ms = round((time.perf_counter() - started) * 1000, 3)
    rss_after_embedding = rss_bytes()
    verifier = NliVerifier()
    started = time.perf_counter()
    verifier.prewarm()
    nli_prewarm_ms = round((time.perf_counter() - started) * 1000, 3)
    rss_after_nli = rss_bytes()
    results = []
    for row in rows:
        sim = float(np.dot(vectors[row["stored_query"]], vectors[row["incoming_query"]]))
        for variant in freeze["comparison"]:
            input_verifier = (
                verifier
                if variant == "current answer assertion"
                else QuestionOnlyInput(verifier, row["stored_answer"])
            )
            started = time.perf_counter()
            decision = policy.decide(
                row["incoming_query"],
                row["stored_query"],
                row["stored_answer"],
                sim,
                input_verifier,
                subject_guard=True,
                technical_guard=False,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            results.append(
                {
                    **row,
                    "variant": variant,
                    "similarity": round(sim, 9),
                    "action": decision.action,
                    "reason": decision.reason,
                    "nli_score": decision.score,
                    "decision_ms": elapsed_ms,
                    "retrieval_eligible": sim >= policy.min_similarity,
                }
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "decisions.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    summary = {
        "workload_sha256": freeze["workload_sha256"],
        "policy_version": policy.version,
        "environment": {
            "rss_initial_bytes": rss_initial,
            "rss_after_embedding_bytes": rss_after_embedding,
            "rss_after_nli_bytes": rss_after_nli,
            "embedding_load_and_encode_ms": embedding_load_ms,
            "nli_prewarm_ms": nli_prewarm_ms,
        },
        "variants": {},
    }
    for variant in freeze["comparison"]:
        subset = [row for row in results if row["variant"] == variant]
        valid = [row for row in subset if row["label"] == "valid"]
        invalid = [row for row in subset if row["label"] == "invalid"]
        ambiguous = [row for row in subset if row["label"] == "abstain"]
        times = [row["decision_ms"] for row in subset]
        summary["variants"][variant] = {
            "valid_reuse": sum(row["action"] == "ACCEPT" for row in valid),
            "valid_denominator": len(valid),
            "missed_valid_reuse": sum(row["action"] != "ACCEPT" for row in valid),
            "invalid_accepts": sum(row["action"] == "ACCEPT" for row in invalid),
            "invalid_denominator": len(invalid),
            "ambiguous_accepts": sum(row["action"] == "ACCEPT" for row in ambiguous),
            "ambiguous_verify": sum(row["action"] == "VERIFY" for row in ambiguous),
            "ambiguous_reject": sum(row["action"] == "REJECT" for row in ambiguous),
            "ambiguous_denominator": len(ambiguous),
            "valid_retrieval_failures": sum(not row["retrieval_eligible"] for row in valid),
            "valid_post_retrieval_misses": sum(
                row["retrieval_eligible"] and row["action"] != "ACCEPT" for row in valid
            ),
            "decision_reasons": dict(Counter(row["reason"] for row in subset)),
            "warm_decision_median_ms": round(statistics.median(times), 3),
            "warm_decision_p95_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 3),
        }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RUN,
        help="new result directory; frozen workload always comes from the versioned source",
    )
    main(parser.parse_args().output_dir)
