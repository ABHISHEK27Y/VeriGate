"""Render the answer-policy report solely from a validated immutable run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "evaluation" / "runs"
REPORT = ROOT / "docs" / "RESULTS_ANSWER_AWARE.md"
# The v6 study was run with dirty source at its recorded HEAD and committed in
# this later revision. Verify those recorded source hashes against that commit.
V6_SOURCE_COMMIT = "ceb520f"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(run_id: str) -> Path:
    folder = RUNS / run_id
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["run_id"] != run_id or manifest["schema_version"] != "answer-policy-run-v1":
        raise ValueError("Incompatible run manifest")
    for name, expected in manifest["outputs"].items():
        if _sha(folder / name) != expected:
            raise ValueError(f"Run artifact changed: {name}")
    if _sha(ROOT / "evaluation" / "answer_aware_holdout.json") != manifest["source_sha256"]:
        raise ValueError("Controlled input changed")
    artifact = ROOT / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
    if _sha(artifact) != manifest["artifact_sha256"]:
        raise ValueError("Policy artifact changed")
    if _sha(ROOT / "evaluation" / "controlled_answer_cases.json") != manifest["development_sha256"]:
        raise ValueError("Static threshold development controls changed")
    for name, expected in manifest["source_hashes"].items():
        source = (
            subprocess.check_output(["git", "show", f"{V6_SOURCE_COMMIT}:{name}"], cwd=ROOT)
            if run_id == "answer_aware_20261029_v6"
            else (ROOT / name).read_bytes()
        )
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError(f"Study source changed: {name}")
    with (folder / "metrics.csv").open(newline="", encoding="utf-8") as stream:
        metrics = list(csv.DictReader(stream))
    with (folder / "decisions.csv").open(newline="", encoding="utf-8") as stream:
        decisions = list(csv.DictReader(stream))
    lines = [
        "# Answer-aware cache: controlled local comparison",
        "",
        f"Run: `{run_id}` · policy artifact: `{manifest['artifact_version'][:12]}` · "
        f"source revision at run: `{manifest['commit'][:12]}`.",
        "The manifest hashes the controlled input, policy, decisions, metrics, and figure.",
        "All 60 binary cases were authored for this study from 20 fact families; two",
        "ambiguous cases were excluded from error-rate denominators. This is a",
        "development benchmark, not an independent production sample.",
        "",
        "| Policy | Accepted / 60 | Incorrect accepted | Incorrect / accepted | "
        "VERIFY / 62 | Warm decision p50 / p95 ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in metrics:
        error = (
            f"{float(row['incorrect_accept_rate']):.1%}"
            if row["incorrect_accept_rate"]
            else "undefined"
        )
        lines.append(
            f"| {row['system']} | {row['accepted']} / {row['known']} "
            f"| {row['incorrect_accepted']} | {error} | {row['verify']} "
            f"| {float(row['decision_p50_ms']):.2f} / "
            f"{float(row['decision_p95_ms']):.2f} |"
        )
    lines.extend(
        (
            "",
            "### Answer-aware results by case type",
            "",
            "| Category | Cases | ACCEPT | VERIFY | Incorrect ACCEPT |",
            "|---|---:|---:|---:|---:|",
        )
    )
    for category in ("valid_paraphrase", "changed_fact", "conflicting_answer", "ambiguous"):
        group = [
            row
            for row in decisions
            if row["system"] == "answer_aware_v1" and row["category"] == category
        ]
        lines.append(
            f"| {category} | {len(group)} | "
            f"{sum(row['action'] == 'ACCEPT' for row in group)} | "
            f"{sum(row['action'] == 'VERIFY' for row in group)} | "
            f"{sum(row['action'] == 'ACCEPT' and row['valid'] == 'False' for row in group)} |"
        )
    lines.extend(
        (
            "",
            f"![Coverage and incorrect accepts](../evaluation/runs/{run_id}/comparison.png)",
            "",
            "The exact baseline has no candidate hit on these changed questions. The",
            "historical static and adaptive policies use query-only decisions. A separate",
            "static baseline was tuned on 15 earlier controls "
            f"(threshold {manifest['tuned_static_threshold']:.2f}).",
            "The new",
            "policy checks the specific cached answer with a pinned NLI model and routes",
            "uncertain candidates to the provider. REJECT also proceeds to the provider",
            "in the gateway; it never returns the rejected cached answer. The two",
            "ambiguous cases were not accepted by the answer-aware policy.",
            "",
            f"Model-load time was {manifest['cold_model_load_ms']:.0f} ms in this local run.",
            "Latency is warm candidate-decision time only. It excludes embedding,",
            "retrieval, network and provider generation. The `hash` embedding backend",
            "is lexical and the 0.72 static threshold was historical, not retuned for",
            "this controlled set. No cloud monetary saving or formal risk guarantee follows.",
            "",
            "The policy has a 0.9 NLI acceptance threshold and a 0.2 rejection threshold",
            "from its frozen artifact. These settings were chosen before the saved run,",
            "but the cases and policy are both authored locally; independent transfer",
            "validation is still needed. The earlier FLAN judge is excluded from",
            "acceptance because it missed every positive validation case.",
            "",
        )
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return REPORT


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    print(run(parser.parse_args().run_id))
