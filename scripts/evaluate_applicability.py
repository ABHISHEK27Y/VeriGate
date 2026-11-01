"""Compare a frozen applicability guard with the unchanged answer policy."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import time
from pathlib import Path

import numpy as np

from app.cache.answer_policy import AnswerDecision, AnswerPolicy
from app.cache.applicability import assess as assess_applicability
from app.cache.verifier import NliVerifier
from app.config import get_settings
from app.embeddings import Embedder
from scripts.evaluate_bidirectional_answer import MeasuringVerifier, rss_bytes

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation/runs/technical_applicability_lockbox_20261101_v1"
POLICY = ROOT / "app/cache/artifacts/answer_policy_v1.json"


def main(output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    workload = SOURCE / "workload.json"
    freeze = json.loads((SOURCE / "freeze.json").read_text(encoding="utf-8"))
    if hashlib.sha256(workload.read_bytes()).hexdigest() != freeze["workload_sha256"]:
        raise ValueError("Frozen workload changed")
    if hashlib.sha256(POLICY.read_bytes()).hexdigest() != freeze["policy_artifact_sha256"]:
        raise ValueError("Pinned policy changed")
    families = json.loads(workload.read_text(encoding="utf-8"))
    if (
        len(families) != freeze["families"]
        or sum(len(f["cases"]) for f in families) != freeze["cases"]
    ):
        raise ValueError("Frozen case count changed")
    policy = AnswerPolicy.load(POLICY)
    rss_initial = rss_bytes()
    embedder = Embedder()
    texts = {
        q
        for family in families
        for q in (family["stored_query"], *(case["incoming_query"] for case in family["cases"]))
    }
    vectors = {text: embedder.embed(text) for text in texts}
    rss_after_embedding = rss_bytes()
    verifier = NliVerifier()
    started = time.perf_counter()
    verifier.prewarm()
    prewarm_ms = (time.perf_counter() - started) * 1000
    rss_after_nli = rss_bytes()
    results = []
    for family in families:
        stored, answer = family["stored_query"], family["stored_answer"]
        for case in family["cases"]:
            incoming = case["incoming_query"]
            similarity = float(np.dot(vectors[stored], vectors[incoming]))
            for variant in freeze["variants"]:
                verifier.cache.clear()
                measured = MeasuringVerifier(verifier)
                started = time.perf_counter()
                applicability = (
                    assess_applicability(incoming, stored, answer)
                    if variant == "experimental_applicability"
                    else None
                )
                decision = (
                    AnswerDecision(applicability.action, applicability.reason, None)
                    if applicability is not None
                    else policy.decide(
                        incoming,
                        stored,
                        answer,
                        similarity,
                        measured,
                        subject_guard=True,
                        technical_guard=False,
                    )
                )
                results.append(
                    {
                        "family": family["family"],
                        "domain": family["domain"],
                        "stored_query": stored,
                        "stored_answer": answer,
                        "incoming_query": incoming,
                        "label": case["label"],
                        "contract": case["contract"],
                        "variant": variant,
                        "similarity": round(similarity, 9),
                        "retrieval_eligible": similarity >= policy.min_similarity,
                        "action": decision.action,
                        "reason": decision.reason,
                        "nli_score": decision.score,
                        "applicability_facet": applicability.facet if applicability else None,
                        "applicability_stored_value": applicability.stored_value
                        if applicability
                        else None,
                        "applicability_incoming_value": (
                            applicability.incoming_value if applicability else None
                        ),
                        "decision_ms": round((time.perf_counter() - started) * 1000, 3),
                        "verifier_ms": round(measured.call_ms, 3),
                        "verifier_calls": measured.calls,
                    }
                )
    output.mkdir(parents=True)
    with (output / "decisions.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(results[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)
    summary = {
        "workload_sha256": freeze["workload_sha256"],
        "policy_artifact_sha256": freeze["policy_artifact_sha256"],
        "model": get_settings().nli_model,
        "revision": get_settings().nli_revision,
        "environment": {
            "rss_initial_bytes": rss_initial,
            "rss_after_embedding_bytes": rss_after_embedding,
            "rss_after_nli_bytes": rss_after_nli,
            "rss_after_decisions_bytes": rss_bytes(),
            "nli_prewarm_ms": round(prewarm_ms, 3),
        },
        "variants": {},
    }
    for variant in freeze["variants"]:
        subset = [row for row in results if row["variant"] == variant]
        labelled = {
            label: [row for row in subset if row["label"] == label] for label in freeze["labels"]
        }
        times = [row["decision_ms"] for row in subset]
        verifier_times = [row["verifier_ms"] for row in subset if row["verifier_calls"]]
        summary["variants"][variant] = {
            "valid_reuse": sum(row["action"] == "ACCEPT" for row in labelled["valid"]),
            "valid_denominator": len(labelled["valid"]),
            "valid_retrieval_failures": sum(
                not row["retrieval_eligible"] for row in labelled["valid"]
            ),
            "invalid_accepts": sum(row["action"] == "ACCEPT" for row in labelled["invalid"]),
            "invalid_denominator": len(labelled["invalid"]),
            "ambiguous_accepts": sum(row["action"] == "ACCEPT" for row in labelled["abstain"]),
            "ambiguous_denominator": len(labelled["abstain"]),
            "abstentions": sum(row["action"] == "VERIFY" for row in subset),
            "all_denominator": len(subset),
            "decision_median_ms": round(statistics.median(times), 3),
            "decision_p95_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 3),
            "verifier_calls": sum(row["verifier_calls"] for row in subset),
            "verifier_median_ms": round(statistics.median(verifier_times), 3),
            "verifier_p95_ms": round(
                sorted(verifier_times)[int(0.95 * (len(verifier_times) - 1))], 3
            ),
        }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    main(parser.parse_args().output)
