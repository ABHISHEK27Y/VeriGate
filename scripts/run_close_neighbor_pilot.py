"""Frozen, diagnostic NQ dev close-neighbor comparison with directional references."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from app.cache.answer_policy import AnswerPolicy
from app.cache.policy import CachePolicy
from app.cache.verifier import NliVerifier
from evaluation.gold_answers import cached_answer_reference_match, lenient_reuse_ok
from scripts.run_realistic_query_pilot import ROOT, _exclusions, _norm, _sha, _write_csv

SOURCE = ROOT / "data" / "NQ-open.dev.jsonl"
RANDOM_PILOT = ROOT / "evaluation" / "runs" / "nq_dev_minilm_pilot_v1" / "decisions.csv"
FREEZE = ROOT / "evaluation" / "close_neighbor_freeze_v1.json"
ARTIFACT = ROOT / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
RUNS = ROOT / "evaluation" / "runs"


def _source_rows() -> list[dict]:
    blocked = _exclusions()
    with RANDOM_PILOT.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            blocked.update((_norm(row["incoming_query"]), _norm(row["cached_query"])))
    seen = set(blocked)
    rows = []
    with SOURCE.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            item = json.loads(line)
            question = item["question"].strip()
            norm = _norm(question)
            answers = [answer for answer in item["answer"] if answer.strip()]
            if not question or not answers or norm in seen:
                continue
            seen.add(norm)
            rows.append({"line": line_number, "query": question, "answers": answers})
    return rows


def _candidate_pairs(rows: list[dict], vectors: np.ndarray, freeze: dict) -> list[dict]:
    similarities = vectors @ vectors.T
    positive: list[dict] = []
    negative: list[dict] = []
    threshold = freeze["minimum_minilm_cosine"]
    for i, first in enumerate(rows):
        neighbors = np.flatnonzero(similarities[i, i + 1 :] >= threshold) + i + 1
        for j in neighbors:
            second = rows[j]
            # Direction is fixed by source line: the first question supplies the cached answer.
            proxy = cached_answer_reference_match(first["answers"][0], second["answers"])
            if not proxy and lenient_reuse_ok(first["answers"], second["answers"]):
                continue  # ambiguous granularity or aliases are not forced into negatives
            pair = {
                "family_id": f"nq-dev:{first['line']}:{second['line']}",
                "cached_line": first["line"],
                "cached_query": first["query"],
                "cached_answer": first["answers"][0],
                "incoming_line": second["line"],
                "incoming_query": second["query"],
                "proxy_reference_match": proxy,
                "similarity": float(similarities[i, j]),
                "selection_key": hashlib.sha256(
                    f"{freeze['selection_seed']}:{first['line']}:{second['line']}".encode()
                ).hexdigest(),
            }
            (positive if proxy else negative).append(pair)
    used: set[int] = set()
    selected = []
    for pool, count in (
        (positive, freeze["proxy_positive_pairs"]),
        (negative, freeze["proxy_negative_pairs"]),
    ):
        accepted = 0
        for pair in sorted(pool, key=lambda candidate: candidate["selection_key"]):
            if pair["cached_line"] in used or pair["incoming_line"] in used:
                continue
            selected.append(pair)
            used.update((pair["cached_line"], pair["incoming_line"]))
            accepted += 1
            if accepted == count:
                break
        if accepted != count:
            raise ValueError(f"Only {accepted} disjoint pairs available for target {count}")
    return sorted(selected, key=lambda pair: pair["family_id"])


def run(run_id: str) -> Path:  # noqa: PLR0915 - creates one immutable run
    if not run_id.isidentifier():
        raise ValueError("run_id must be an identifier")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if _sha(SOURCE) != freeze["source_sha256"]:
        raise ValueError("NQ dev input differs from freeze")
    if _sha(ARTIFACT) != freeze["answer_policy_artifact_sha256"]:
        raise ValueError("Answer policy artifact differs from freeze")
    target = RUNS / run_id
    target.mkdir(parents=True, exist_ok=False)
    source_rows = _source_rows()
    model = SentenceTransformer(freeze["embedding_model"], revision=freeze["embedding_revision"])
    vectors = np.asarray(
        model.encode(
            [row["query"] for row in source_rows],
            batch_size=64,
            normalize_embeddings=True,
            show_progress_bar=False,
        ),
        dtype=np.float32,
    )
    pairs = _candidate_pairs(source_rows, vectors, freeze)
    answer_policy = AnswerPolicy.load(ARTIFACT)
    verifier = NliVerifier()
    verifier.entail_prob("A test answer is available.", "A test answer is available.")
    if verifier.unavailable:
        raise RuntimeError("Pinned NLI verifier unavailable")
    static = CachePolicy(use_adaptive=False, use_verifier=False, static_threshold=0.72)
    adaptive = CachePolicy(use_nli=False)
    systems = ("exact", "static_0.72", "adaptive_tier1", "answer_aware_v1")
    decisions = []
    for pair in pairs:
        for system in systems:
            start = time.perf_counter_ns()
            if system == "exact":
                action, reason = "REJECT", "exact_miss"  # all selected pairs are distinct
            elif system == "answer_aware_v1":
                decision = answer_policy.decide(
                    pair["incoming_query"],
                    pair["cached_query"],
                    pair["cached_answer"],
                    pair["similarity"],
                    verifier,
                )
                action, reason = decision.action, decision.reason
            else:
                policy = static if system == "static_0.72" else adaptive
                accepted, reason, _ = policy.decide(
                    pair["incoming_query"], pair["cached_query"], pair["similarity"]
                )
                action = "ACCEPT" if accepted else "REJECT"
            decisions.append(
                {
                    "family_id": pair["family_id"],
                    "cached_line": pair["cached_line"],
                    "cached_query": pair["cached_query"],
                    "cached_answer": pair["cached_answer"],
                    "incoming_line": pair["incoming_line"],
                    "incoming_query": pair["incoming_query"],
                    "proxy_reference_match": pair["proxy_reference_match"],
                    "similarity": pair["similarity"],
                    "system": system,
                    "action": action,
                    "reason": reason,
                    "decision_ms": round((time.perf_counter_ns() - start) / 1_000_000, 6),
                    "label_type": freeze["label_type"],
                }
            )
    _write_csv(target / "decisions.csv", decisions)
    summaries = []
    for system in systems:
        subset = [row for row in decisions if row["system"] == system]
        latencies = np.asarray([row["decision_ms"] for row in subset])
        summaries.append(
            {
                "system": system,
                "n": len(subset),
                "proxy_positive_n": sum(row["proxy_reference_match"] for row in subset),
                "proxy_negative_n": sum(not row["proxy_reference_match"] for row in subset),
                "accept": sum(row["action"] == "ACCEPT" for row in subset),
                "verify": sum(row["action"] == "VERIFY" for row in subset),
                "reject": sum(row["action"] == "REJECT" for row in subset),
                "accepted_reference_match": sum(
                    row["action"] == "ACCEPT" and row["proxy_reference_match"] for row in subset
                ),
                "accepted_reference_mismatch": sum(
                    row["action"] == "ACCEPT" and not row["proxy_reference_match"] for row in subset
                ),
                "decision_p50_ms": float(np.median(latencies)),
                "decision_p95_ms": float(np.quantile(latencies, 0.95)),
                "label_type": freeze["label_type"],
            }
        )
    _write_csv(target / "metrics.csv", summaries)
    manifest = {
        "schema_version": "close-neighbor-pilot-v1",
        "run_id": run_id,
        "freeze_sha256": _sha(FREEZE),
        "source_sha256": _sha(SOURCE),
        "excluded_random_pilot_sha256": _sha(RANDOM_PILOT),
        "mined_train_sha256": _sha(ROOT / "data" / "gold_answer_pairs.tsv"),
        "eligible_questions": len(source_rows),
        "selected_pairs": len(pairs),
        "selected_question_lines_sha256": hashlib.sha256(
            json.dumps([(pair["cached_line"], pair["incoming_line"]) for pair in pairs]).encode()
        ).hexdigest(),
        "answer_policy_artifact_sha256": _sha(ARTIFACT),
        "nli_model": answer_policy.model,
        "nli_revision": answer_policy.revision,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "label_type": freeze["label_type"],
        "source_code_sha256": {
            name: _sha(ROOT / name)
            for name in (
                "app/cache/answer_policy.py",
                "app/cache/policy.py",
                "app/cache/verifier.py",
                "scripts/run_close_neighbor_pilot.py",
            )
        },
        "outputs": {name: _sha(target / name) for name in ("decisions.csv", "metrics.csv")},
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", nargs="?", default="nq_dev_close_neighbors_v1")
    print(run(parser.parse_args().run_id))
