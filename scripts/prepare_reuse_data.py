"""Export labelled candidate/probe pairs without inventing truth labels."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.cache.reuse_verifier import sha256_file

FIELDS = (
    "source",
    "family",
    "stored_question",
    "stored_answer",
    "incoming_question",
    "reuse_ok",
    "label_provenance",
)


def export(source: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError("Label export does not overwrite prior evidence")
    workload = json.loads(source.read_text(encoding="utf-8"))
    rows = []
    for family in workload:
        for probe in family["probes"]:
            suitable = set(probe["suitable"])
            for index, candidate in enumerate(family["candidates"]):
                rows.append(
                    {
                        "source": source.parent.name,
                        "family": family["family"],
                        "stored_question": candidate["question"],
                        "stored_answer": candidate["answer"],
                        "incoming_question": probe["question"],
                        "reuse_ok": str(int(index in suitable)),
                        "label_provenance": "authored_suitability_development",
                    }
                )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "input": str(source),
        "input_sha256": sha256_file(source),
        "output_sha256": sha256_file(output),
        "rows": len(rows),
        "families": len(workload),
        "label_provenance": "authored_suitability_development",
        "warning": "Inspected authored examples; development only, not independent test truth",
    }
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.source, args.output)
