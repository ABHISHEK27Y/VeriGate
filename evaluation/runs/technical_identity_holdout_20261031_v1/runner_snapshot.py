"""Freeze authored technical cases before comparing the live HTTP guard modes."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
from collections import Counter
from pathlib import Path

from scripts.stress_semantic_http import POLICY, digest, run_one, write_csv

# New scenarios, separate from the developer-written identity unit cases.
# Answers are stipulated controls, not verified vendor documentation.
FAMILIES = (
    (
        "nginx",
        "How do I restart Nginx in staging?",
        "How can I reboot Nginx in stage?",
        "How do I restart Nginx in production?",
        "Use the staging service restart command.",
        "Use the production service restart command.",
    ),
    (
        "mysql",
        "How do I backup MySQL?",
        "What is the way to make a MySQL backup?",
        "How do I restore MySQL?",
        "Run a backup command.",
        "Run a restore command.",
    ),
    (
        "fastapi",
        "How do I update `USER_OUT` in FastAPI?",
        "How can I modify `USER_OUT` in FastAPI?",
        "How do I update `USER_IN` in FastAPI?",
        "Change the output schema.",
        "Change the input schema.",
    ),
    (
        "s3",
        "How do I enable a public S3 policy?",
        "How can I activate a public S3 policy?",
        "How do I disable a public S3 policy?",
        "Enable the public policy.",
        "Disable the public policy.",
    ),
    (
        "git",
        "How do I create a Git branch?",
        "How can I add a Git branch?",
        "How do I delete a Git branch?",
        "Create a branch.",
        "Delete a branch.",
    ),
    (
        "linux",
        "How do I restart a Linux service?",
        "How can I reboot a Linux service?",
        "How do I stop a Linux service?",
        "Restart the service.",
        "Stop the service.",
    ),
    (
        "nodejs",
        "How do I deploy Node.js 18?",
        "How can I release Node.js 18?",
        "How do I deploy Node.js 20?",
        "Deploy version 18.",
        "Deploy version 20.",
    ),
)


def build(output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    rows: list[dict] = []
    answers = {}
    for index, (domain, seed, valid, invalid, original, changed) in enumerate(FAMILIES):
        for kind, question, answer, relation in (
            ("seed", seed, original, "seed"),
            ("paraphrase", valid, original, "valid"),
            ("near_match", invalid, changed, "invalid"),
        ):
            answers[question] = answer
            rows.append(
                {
                    "id": f"{domain}-{index}:{kind}",
                    "family_id": f"{domain}-{index}",
                    "kind": kind,
                    "domain": domain,
                    "question": question,
                    "reference_answer": answer,
                    "relation": relation,
                    "evidence": "authored controlled scenario; stipulated answer",
                    "label_status": "authored_control",
                    "uncertainty": "No independent factual review; tests reuse consistency only",
                    "position": len(rows) + 1,
                }
            )
    if len(answers) != len(rows):
        raise ValueError("Repeated technical question")
    output.mkdir(parents=True)
    write_csv(output / "workload.csv", rows)
    (output / "provider_answers.json").write_text(json.dumps(answers, indent=2), encoding="utf-8")
    freeze = {
        "requests": len(rows),
        "source": "new authored technical scenarios",
        "selection": (
            "7 disjoint scenarios in Nginx, MySQL, FastAPI, S3, Git, Linux, and "
            "Node.js; seed, paraphrase, near match"
        ),
        "label_limit": "Stipulated controls, not independently verified technical answers",
        "workload_sha256": digest(output / "workload.csv"),
        "provider_answers_sha256": digest(output / "provider_answers.json"),
        "policy_sha256": digest(POLICY),
        "comparison": {"unchanged": False, "technical_guard": True},
        "settings": {
            mode: {"cache_ttl_sec": 86400, "max_cache_entries_per_tenant": 256}
            for mode in ("unchanged", "technical_guard")
        },
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "nli_model": "cross-encoder/nli-deberta-v3-xsmall",
        "nli_revision": "a150876415327c80daeff35ca6f68f5ed8cf5c24",
    }
    (output / "freeze.json").write_text(json.dumps(freeze, indent=2), encoding="utf-8")


async def run(output: Path) -> None:
    freeze = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    for path, key in (
        (output / "workload.csv", "workload_sha256"),
        (output / "provider_answers.json", "provider_answers_sha256"),
        (POLICY, "policy_sha256"),
    ):
        if digest(path) != freeze[key]:
            raise ValueError(f"Frozen input changed: {path}")
    with (output / "workload.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    answers = json.loads((output / "provider_answers.json").read_text(encoding="utf-8"))
    original = os.environ.get("ANSWER_POLICY_TECHNICAL_GUARD")
    try:
        for mode, guard in freeze["comparison"].items():
            if (output / f"answer_aware_{mode}").exists():
                raise FileExistsError(mode)
            os.environ["ANSWER_POLICY_TECHNICAL_GUARD"] = str(guard).lower()
            summary = await run_one(output, "answer_aware", mode, rows, answers, freeze)
            manifest_path = output / f"answer_aware_{mode}" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["config"]["ANSWER_POLICY_TECHNICAL_GUARD"] = str(guard).lower()
            manifest["runner_sha256"] = digest(Path(__file__))
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(json.dumps(summary), flush=True)
    finally:
        if original is None:
            os.environ.pop("ANSWER_POLICY_TECHNICAL_GUARD", None)
        else:
            os.environ["ANSWER_POLICY_TECHNICAL_GUARD"] = original


def analyze(output: Path) -> None:
    freeze = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    summaries = []
    for mode in freeze["comparison"]:
        directory = output / f"answer_aware_{mode}"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if digest(directory / "requests.csv") != manifest["requests_sha256"]:
            raise ValueError("Saved observations changed")
        with (directory / "requests.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        valid = [row for row in rows if row["relation"] == "valid"]
        invalid = [row for row in rows if row["relation"] == "invalid"]
        times = [float(row["http_latency_ms"]) for row in rows if row["http_status"] == "200"]
        summaries.append(
            {
                "mode": mode,
                "requests": len(rows),
                "completed": sum(row["http_status"] == "200" for row in rows),
                "valid_reuse": sum(row["outcome"] == "correct_hit" for row in valid),
                "valid_denominator": len(valid),
                "incorrect_accepts": sum(
                    row["outcome"] == "incorrect_acceptance" for row in invalid
                ),
                "invalid_denominator": len(invalid),
                "provider_calls": sum(row["provider_invoked"] == "True" for row in rows),
                "median_http_ms": round(statistics.median(times), 3),
                "p95_http_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 3),
                "outcomes": dict(Counter(row["outcome"] for row in rows)),
            }
        )
    (output / "comparison.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "run", "analyze"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.action == "build":
        build(output)
    elif args.action == "run":
        asyncio.run(run(output))
    else:
        analyze(output)


if __name__ == "__main__":
    main()
