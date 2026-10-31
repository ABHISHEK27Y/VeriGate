"""Re-run the frozen failed workload with the new guard as development evidence."""

from __future__ import annotations

import asyncio
import csv
import json
import shutil
from pathlib import Path

from scripts.stress_semantic_http import POLICY, ROOT, digest, run_one

SOURCE = ROOT / "evaluation/runs/nq_song_stress_20261030_v3"


async def run(output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    original = json.loads((SOURCE / "freeze.json").read_text(encoding="utf-8"))
    for name, expected in (
        ("workload.csv", original["workload_sha256"]),
        ("provider_answers.json", original["provider_answers_sha256"]),
    ):
        if digest(SOURCE / name) != expected:
            raise ValueError(f"Frozen development input changed: {name}")
    if digest(POLICY) != original["policy_sha256"]:
        raise ValueError("Frozen answer-policy artifact changed")
    output.mkdir(parents=True)
    for name in ("workload.csv", "provider_answers.json", "freeze.json", "DATA_LICENSE.md"):
        shutil.copyfile(SOURCE / name, output / name)
    (output / "DEVELOPMENT_ONLY.md").write_text(
        "This reuses the inspected v3 song stress workload. It is development "
        "evidence, not a fresh held-out test. The earlier run remains untouched.\n",
        encoding="utf-8",
    )
    with (output / "workload.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    answers = json.loads((output / "provider_answers.json").read_text(encoding="utf-8"))
    summary = await run_one(output, "answer_aware", "sufficient", rows, answers, original)
    manifest_path = output / "answer_aware_sufficient/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["config"]["ANSWER_POLICY_SUBJECT_GUARD"] = "true"
    manifest["source_run"] = SOURCE.name
    manifest["runner_sha256"] = digest(Path(__file__))
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    asyncio.run(run(parser.parse_args().output.resolve()))
