"""Descriptive NQ-Open dev pilot; no answer-reuse correctness labels are inferred."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import time
from pathlib import Path

import numpy as np

from app.cache.answer_policy import AnswerPolicy
from app.cache.policy import CachePolicy
from app.cache.verifier import NliVerifier
from app.config import get_settings
from app.embeddings import Embedder

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "evaluation" / "pilot_freeze_nq_dev_v1.json"
SOURCE = ROOT / "data" / "NQ-open.dev.jsonl"
DEV = ROOT / "evaluation" / "controlled_answer_cases.json"
HELDOUT = ROOT / "evaluation" / "answer_aware_holdout.json"
MINED = ROOT / "data" / "gold_answer_pairs.tsv"
RUNS = ROOT / "evaluation" / "runs"
SIMILARITY_DENSITY_WINDOW = 0.1


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _norm(question: str) -> str:
    return " ".join(question.casefold().split())


def _exclusions() -> set[str]:
    blocked: set[str] = set()
    for row in json.loads(DEV.read_text(encoding="utf-8")):
        blocked.update(_norm(row[key]) for key in ("stored", "incoming"))
    for row in json.loads(HELDOUT.read_text(encoding="utf-8")):
        blocked.update(_norm(row[key]) for key in ("stored", "valid", "invalid"))
        blocked.add(_norm(f"Is the answer to '{row['stored']}' {row['invalid_answer']}?"))
    with MINED.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            blocked.update(_norm(row[key]) for key in ("stored_query", "incoming_query"))
    return blocked


def _select(freeze: dict) -> tuple[list[dict], list[dict], int]:
    blocked = _exclusions()
    seen = set(blocked)
    eligible = []
    with SOURCE.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            item = json.loads(line)
            question = item["question"].strip()
            answers = item["answer"]
            normalized = _norm(question)
            if not question or not answers or not answers[0].strip() or normalized in seen:
                continue
            seen.add(normalized)
            eligible.append(
                {
                    "source_line": line_number,
                    "query": question,
                    "answer": answers[0],
                    "sort_key": hashlib.sha256(f"pilot-v1:{normalized}".encode()).hexdigest(),
                }
            )
    eligible.sort(key=lambda row: (row["sort_key"], row["source_line"]))
    selection = freeze["selection"]
    stored_count = selection["stored_count"]
    incoming_count = selection["distinct_incoming_count"]
    if len(eligible) < stored_count + incoming_count:
        raise ValueError("Too few non-overlapping NQ dev questions")
    return (
        eligible[:stored_count],
        eligible[stored_count : stored_count + incoming_count],
        len(eligible),
    )


def _validate_freeze(freeze: dict) -> AnswerPolicy:
    settings = get_settings()
    if _sha(SOURCE) != freeze["source_sha256"]:
        raise ValueError("NQ dev input differs from frozen SHA-256")
    artifact = ROOT / freeze["policy"]["artifact"]
    if _sha(artifact) != freeze["policy"]["artifact_sha256"]:
        raise ValueError("Answer-policy artifact differs from frozen SHA-256")
    policy = AnswerPolicy.load(artifact)
    expected = freeze["policy"]
    if (
        policy.accept_at != expected["accept_at"]
        or policy.reject_below != expected["reject_below"]
        or policy.min_similarity != expected["min_similarity"]
        or policy.model != expected["nli_model"]
        or policy.revision != expected["nli_revision"]
    ):
        raise ValueError("Answer-policy settings differ from freeze")
    embedding = freeze["embedding"]
    if (
        settings.embedding_backend != embedding["backend"]
        or settings.embedding_model != embedding["model"]
        or settings.embedding_revision != embedding["revision"]
        or settings.nli_model != policy.model
        or settings.nli_revision != policy.revision
    ):
        raise ValueError("Model configuration differs from freeze")
    return policy


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(run_id: str) -> Path:  # noqa: PLR0915 - one immutable pilot run
    if not run_id.isidentifier():
        raise ValueError("run_id must be an identifier")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    policy = _validate_freeze(freeze)
    stored, incoming, eligible_count = _select(freeze)
    selected = [*incoming, *stored[: freeze["selection"]["exact_repeat_count"]]]
    target = RUNS / run_id
    target.mkdir(parents=True, exist_ok=False)
    embedder = Embedder()
    verifier = NliVerifier()
    # Load both models before timing; the run reports warm lookup only.
    embedder.embed("model warmup query")
    verifier.entail_prob("The answer to a test is a test answer.", "The answer is a test answer.")
    if verifier.unavailable:
        raise RuntimeError("Pinned NLI verifier unavailable")
    stored_vectors = np.stack([embedder.embed(item["query"]) for item in stored])
    static = CachePolicy(use_adaptive=False, use_verifier=False, static_threshold=0.72)
    adaptive = CachePolicy(use_nli=False)
    systems = ("exact", "static_0.72", "adaptive_tier1", "answer_aware_v1")
    rows = []
    for item in selected:
        retrieval_start = time.perf_counter_ns()
        vector = embedder.embed(item["query"])
        similarities = stored_vectors @ vector
        index = int(np.argmax(similarities))
        candidate = stored[index]
        similarity = float(similarities[index])
        within = int(
            np.count_nonzero(
                (similarities < similarity)
                & (similarity - similarities <= SIMILARITY_DENSITY_WINDOW)
            )
        )
        density = min(1.0, within / len(similarities))
        retrieval_ms = (time.perf_counter_ns() - retrieval_start) / 1_000_000
        for system in systems:
            start = time.perf_counter_ns()
            if system == "exact":
                action = "ACCEPT" if item["query"] == candidate["query"] else "REJECT"
                reason = "exact_key" if action == "ACCEPT" else "exact_miss"
            elif system == "answer_aware_v1":
                result = policy.decide(
                    item["query"], candidate["query"], candidate["answer"], similarity, verifier
                )
                action, reason = result.action, result.reason
            else:
                contender = static if system == "static_0.72" else adaptive
                accepted, reason, _ = contender.decide(
                    item["query"], candidate["query"], similarity, density
                )
                action = "ACCEPT" if accepted else "REJECT"
            decision_ms = (time.perf_counter_ns() - start) / 1_000_000
            rows.append(
                {
                    "source_line": item["source_line"],
                    "incoming_query": item["query"],
                    "cached_source_line": candidate["source_line"],
                    "cached_query": candidate["query"],
                    "cached_answer": candidate["answer"],
                    "candidate_type": "exact_repeat" if item in stored else "nearest_distinct",
                    "system": system,
                    "similarity": similarity,
                    "density": density,
                    "action": action,
                    "reason": reason,
                    "warm_decision_ms": round(decision_ms, 6),
                    "warm_local_lookup_ms": round(
                        decision_ms + (0 if system == "exact" else retrieval_ms), 6
                    ),
                    "label_type": "unlabelled_nq_reference",
                }
            )
    _write_csv(target / "decisions.csv", rows)
    summary = []
    for system in systems:
        subset = [row for row in rows if row["system"] == system]
        decision = np.array([row["warm_decision_ms"] for row in subset])
        lookup = np.array([row["warm_local_lookup_ms"] for row in subset])
        summary.append(
            {
                "system": system,
                "n": len(subset),
                "accepted": sum(row["action"] == "ACCEPT" for row in subset),
                "coverage": sum(row["action"] == "ACCEPT" for row in subset) / len(subset),
                "verify": sum(row["action"] == "VERIFY" for row in subset),
                "reject": sum(row["action"] == "REJECT" for row in subset),
                "decision_p50_ms": float(np.median(decision)),
                "decision_p95_ms": float(np.quantile(decision, 0.95)),
                "local_lookup_p50_ms": float(np.median(lookup)),
                "local_lookup_p95_ms": float(np.quantile(lookup, 0.95)),
                "label_type": "unlabelled_nq_reference",
            }
        )
    _write_csv(target / "metrics.csv", summary)
    manifest = {
        "schema_version": "realistic-query-pilot-v1",
        "run_id": run_id,
        "freeze_sha256": _sha(FREEZE),
        "source_sha256": _sha(SOURCE),
        "development_sha256": _sha(DEV),
        "heldout_sha256": _sha(HELDOUT),
        "mined_train_pairs_sha256": _sha(MINED),
        "eligible_source_rows": eligible_count,
        "stored_rows": len(stored),
        "incoming_rows": len(selected),
        "selected_questions_sha256": hashlib.sha256(
            "\n".join(item["query"] for item in [*stored, *selected]).encode()
        ).hexdigest(),
        "artifact_sha256": _sha(ROOT / freeze["policy"]["artifact"]),
        "artifact_version": policy.version,
        "embedding_model": freeze["embedding"],
        "nli_model": policy.model,
        "nli_revision": policy.revision,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sentence_transformers": importlib.metadata.version("sentence-transformers"),
        "git_commit_at_run": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "latency_scope": (
            "warm local query embedding, nearest-neighbor retrieval and policy decision; "
            "excludes Redis, HTTP and provider"
        ),
        "label_type": "unlabelled_nq_reference",
        "outputs": {name: _sha(target / name) for name in ("decisions.csv", "metrics.csv")},
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", nargs="?", default="nq_dev_minilm_pilot_v1")
    print(run(parser.parse_args().run_id))
