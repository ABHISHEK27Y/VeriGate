"""Inspect actual pinned NLI pair tokenization without running inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from transformers import AutoTokenizer

MODEL = "cross-encoder/nli-deberta-v3-xsmall"
REVISION = "a150876415327c80daeff35ca6f68f5ed8cf5c24"


def run(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    limit = int(tokenizer.model_max_length)
    # Same byte size, different subword segmentation: byte count cannot stand
    # in for the model's complete paired token sequence.
    cases = []
    for word in ("a", "q", "xy", "zq", "123"):
        premise = "The answer to " + (word + " ") * 160 + "is x."
        hypothesis = premise
        pair = tokenizer(premise, hypothesis, truncation=False, add_special_tokens=True)
        cases.append(
            {
                "word": word,
                "assertion_bytes": len(premise.encode()),
                "combined_tokens": len(pair["input_ids"]),
                "fits": len(pair["input_ids"]) <= limit,
            }
        )
    result = {
        "schema_version": "pinned-nli-window-v1",
        "model": MODEL,
        "revision": REVISION,
        "tokenizer_limit": limit,
        "cases": cases,
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not (cases[0]["fits"] and not cases[2]["fits"] and cases[4]["fits"]):
        raise AssertionError("Expected actual paired-token boundary was not observed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    print(json.dumps(run(parser.parse_args().output), indent=2))
