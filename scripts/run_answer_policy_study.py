"""Save an immutable controlled comparison of the opt-in answer policy."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.cache.answer_policy import AnswerPolicy  # noqa: E402
from app.cache.policy import CachePolicy  # noqa: E402
from app.cache.verifier import NliVerifier  # noqa: E402
from app.embeddings import Embedder  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation" / "answer_aware_holdout.json"
ARTIFACT = ROOT / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
DEVELOPMENT = ROOT / "evaluation" / "controlled_answer_cases.json"
RUNS = ROOT / "evaluation" / "runs"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cases() -> list[dict]:
    families = json.loads(SOURCE.read_text(encoding="utf-8"))
    if len({f["family"] for f in families}) != len(families):
        raise ValueError("Duplicate controlled family")
    rows: list[dict] = []
    for family in families:
        base = {
            "family": family["family"],
            "stored": family["stored"],
            "answer": family["answer"],
            "split": "heldout_controlled",
        }
        rows.extend(
            (
                {
                    **base,
                    "id": f"{family['family']}:valid",
                    "incoming": family["valid"],
                    "category": "valid_paraphrase",
                    "valid": True,
                },
                {
                    **base,
                    "id": f"{family['family']}:invalid",
                    "incoming": family["invalid"],
                    "category": "changed_fact",
                    "valid": False,
                },
                {
                    **base,
                    "id": f"{family['family']}:conflict",
                    "incoming": (
                        f"Is the answer to '{family['stored']}' {family['invalid_answer']}?"
                    ),
                    "category": "conflicting_answer",
                    "valid": False,
                },
            )
        )
    rows.extend(
        (
            {
                "family": "congo_ambiguous",
                "stored": "What is the capital of Congo?",
                "answer": "Brazzaville",
                "incoming": "Name the capital of Congo.",
                "split": "heldout_controlled",
                "id": "congo:ambiguous",
                "category": "ambiguous",
                "valid": None,
            },
            {
                "family": "springfield_ambiguous",
                "stored": "Where is Springfield?",
                "answer": "Illinois",
                "incoming": "Where is Springfield located?",
                "split": "heldout_controlled",
                "id": "springfield:ambiguous",
                "category": "ambiguous",
                "valid": None,
            },
        )
    )
    development = json.loads(DEVELOPMENT.read_text(encoding="utf-8"))
    development_questions = {
        row[key].casefold().strip() for row in development for key in ("stored", "incoming")
    }
    if any(
        row[key].casefold().strip() in development_questions
        for row in rows
        for key in ("stored", "incoming")
    ):
        raise ValueError("Controlled development/test question overlap")
    return rows


def _tune_static(embedder: Embedder) -> float:
    """Select the query-only F1 threshold on the separate development controls."""
    development = [
        row
        for row in json.loads(DEVELOPMENT.read_text(encoding="utf-8"))
        if row["valid"] is not None
    ]
    scored = [
        (
            float(np.dot(embedder.embed(row["stored"]), embedder.embed(row["incoming"]))),
            bool(row["valid"]),
        )
        for row in development
    ]
    best_score, best_threshold = -1.0, 1.0
    for step in range(20, 101):
        threshold = step / 100
        tp = sum(score >= threshold and valid for score, valid in scored)
        fp = sum(score >= threshold and not valid for score, valid in scored)
        fn = sum(score < threshold and valid for score, valid in scored)
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
        if f1 > best_score or (f1 == best_score and threshold > best_threshold):
            best_score, best_threshold = f1, threshold
    return best_threshold


def run(run_id: str) -> Path:  # noqa: PLR0915 - writes one complete immutable run
    if not run_id.isidentifier():
        raise ValueError("Use an identifier for run_id")
    target = RUNS / run_id
    target.mkdir(parents=True, exist_ok=False)
    if os.environ.get("EMBEDDING_BACKEND") != "hash":
        raise ValueError("This controlled run requires EMBEDDING_BACKEND=hash")
    policy = AnswerPolicy.load(ARTIFACT)
    verifier = NliVerifier()
    embedder = Embedder()
    tuned_threshold = _tune_static(embedder)
    cases = _cases()
    # Warm model loading is measured separately; no labels or held-out cases are used here.
    start = time.perf_counter()
    verifier.entail_prob(
        "The answer to a test question is a test answer.",
        "The answer to a test question is a test answer.",
    )
    cold_ms = (time.perf_counter() - start) * 1000
    if verifier.unavailable:
        raise RuntimeError("Pinned NLI model is unavailable")
    baselines = {
        "exact": None,
        "static_0.72": CachePolicy(use_adaptive=False, use_verifier=False),
        "static_tuned_dev": CachePolicy(
            use_adaptive=False, use_verifier=False, static_threshold=tuned_threshold
        ),
        "adaptive_tier1": CachePolicy(),
        "answer_aware_v1": policy,
    }
    rows = []
    for case in cases:
        stored_vec = embedder.embed(case["stored"])
        incoming_vec = embedder.embed(case["incoming"])
        similarity = float(np.dot(stored_vec, incoming_vec))
        for name, contender in baselines.items():
            start = time.perf_counter_ns()
            if name == "exact":
                action, reason = (
                    ("ACCEPT", "exact_key")
                    if case["stored"] == case["incoming"]
                    else ("REJECT", "exact_miss")
                )
            elif isinstance(contender, AnswerPolicy):
                decision = contender.decide(
                    case["incoming"], case["stored"], case["answer"], similarity, verifier
                )
                action, reason = decision.action, decision.reason
            else:
                assert isinstance(contender, CachePolicy)
                is_hit, reason, _ = contender.decide(case["incoming"], case["stored"], similarity)
                action = "ACCEPT" if is_hit else "REJECT"
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            rows.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "split": case["split"],
                    "category": case["category"],
                    "system": name,
                    "valid": case["valid"],
                    "action": action,
                    "reason": reason,
                    "similarity": similarity,
                    "decision_latency_ms": elapsed_ms,
                    "label_type": "authored_controlled_answer",
                }
            )
    path = target / "decisions.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for name in baselines:
        subset = [r for r in rows if r["system"] == name]
        known = [r for r in subset if r["valid"] is not None]
        accepted_rows = [r for r in known if r["action"] == "ACCEPT"]
        incorrect = sum(r["valid"] is False for r in accepted_rows)
        latencies = [r["decision_latency_ms"] for r in subset]
        summary.append(
            {
                "system": name,
                "split": "heldout_controlled",
                "known": len(known),
                "ambiguous": len(subset) - len(known),
                "accepted": len(accepted_rows),
                "incorrect_accepted": incorrect,
                "coverage": len(accepted_rows) / len(known),
                "incorrect_accept_rate": incorrect / len(accepted_rows) if accepted_rows else "",
                "verify": sum(r["action"] == "VERIFY" for r in subset),
                "ambiguous_accepted": sum(
                    r["valid"] is None and r["action"] == "ACCEPT" for r in subset
                ),
                "decision_p50_ms": float(np.median(latencies)),
                "decision_p95_ms": float(np.quantile(latencies, 0.95)),
                "label_type": "authored_controlled_answer",
            }
        )
    metrics = target / "metrics.csv"
    with metrics.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)
    figure, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    names = [r["system"] for r in summary]
    axes[0].bar(names, [r["coverage"] for r in summary])
    axes[0].set(ylabel="Accepted / known", ylim=(0, 1))
    axes[1].bar(names, [r["incorrect_accepted"] for r in summary])
    axes[1].set(ylabel="Incorrect accepted count")
    for ax in axes:
        ax.tick_params(axis="x", labelrotation=25)
    figure.tight_layout()
    figure.savefig(target / "comparison.png", dpi=150)
    plt.close(figure)
    manifest = {
        "schema_version": "answer-policy-run-v1",
        "run_id": run_id,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": _sha(SOURCE),
        "artifact_sha256": _sha(ARTIFACT),
        "development_sha256": _sha(DEVELOPMENT),
        "tuned_static_threshold": tuned_threshold,
        "artifact_version": policy.version,
        "source_hashes": {
            name: _sha(ROOT / name)
            for name in (
                "app/cache/answer_policy.py",
                "app/cache/policy.py",
                "app/cache/verifier.py",
                "app/embeddings.py",
                "scripts/run_answer_policy_study.py",
            )
        },
        "embedding_backend": "hash",
        "nli_model": policy.model,
        "nli_revision": policy.revision,
        "cold_model_load_ms": cold_ms,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "notes": (
            "Warm candidate-decision latency; excludes embedding, retrieval and provider time."
        ),
        "outputs": {
            name: _sha(target / name) for name in ("decisions.csv", "metrics.csv", "comparison.png")
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    print(run(parser.parse_args().run_id))
