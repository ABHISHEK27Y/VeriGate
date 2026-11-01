"""Derive directional reference-string labels from the immutable historical NQ file.

This reuses the old pair selection. It does not mine independent examples or create
human answer labels. Refuses to overwrite either output.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from evaluation.gold_answers import cached_answer_reference_match

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "gold_answer_pairs.tsv"
OUTPUT = ROOT / "data" / "answer_pairs_directional.tsv"


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, object]:
    if output.exists() or output.with_suffix(".provenance.json").exists():
        raise FileExistsError(f"Preserving existing directional dataset: {output}")
    positive = uncertain = 0
    with (
        source.open(newline="", encoding="utf-8") as inp,
        output.open("w", newline="", encoding="utf-8") as out,
    ):
        reader = csv.DictReader(inp, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError("Missing source header")
        writer = csv.DictWriter(
            out, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in reader:
            incoming = json.loads(row["incoming_aliases"])
            if not isinstance(incoming, list):
                raise TypeError("Incoming reference answers must be a list")
            matched = cached_answer_reference_match(row["cached_answer"], incoming)
            positive += matched
            uncertain += row["reuse_ok"] == "1" and not matched
            row["reuse_ok"] = str(int(matched))
            row["label_type"] = "cached_answer_reference_match"
            if not matched and not row["negative_type"]:
                row["negative_type"] = "cached_text_absent"
            row["hard_negative"] = str(int(not matched))
            writer.writerow(row)
    manifest: dict[str, object] = {
        "schema_version": "directional-pair-v1",
        "source": "NQ-open historical mined pairs; fixed pair selection",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "derived_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "label_type": "cached_answer_reference_match",
        "positive_reference_matches": positive,
        "historical_positive_now_absent": uncertain,
        "limitation": "Reference-string membership; no independent answer review",
    }
    output.with_suffix(".provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
