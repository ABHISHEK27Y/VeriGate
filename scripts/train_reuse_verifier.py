"""Bounded CPU training for the opt-in three-field reuse classifier.

Input CSV columns: source,family,stored_question,stored_answer,incoming_question,
reuse_ok,label_provenance. Labels must be independently established; this script
rejects model-judged labels and splits whole sources and families before fitting.
It never changes the deployment configuration or an existing artifact.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path

from app.cache.reuse_verifier import FORMAT_VERSION, format_input, sha256_file
from app.config import settings

MIN_ROWS = 600
MIN_SOURCES = 3
MIN_ACCEPTS = 59  # zero errors on a held-out audit approaches a 5% one-sided bound
MAX_ROWS = 4000
EPOCHS = 2
BATCH_SIZE = 4
SEED = 71
NEAR_DUPLICATE_THRESHOLD = 0.9
TARGET_ERROR_BOUND = 0.05
ALLOWED_PROVENANCE = {"expert_reviewed", "source_document_verified"}


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    fields = {
        "source",
        "family",
        "stored_question",
        "stored_answer",
        "incoming_question",
        "reuse_ok",
        "label_provenance",
    }
    if not rows or not fields <= rows[0].keys():
        raise ValueError(f"Training CSV requires fields: {sorted(fields)}")
    if len(rows) < MIN_ROWS or len(rows) > MAX_ROWS:
        raise ValueError(f"Need {MIN_ROWS}..{MAX_ROWS} independently labelled rows")
    for row in rows:
        if row["reuse_ok"] not in {"0", "1"}:
            raise ValueError("Unresolved labels cannot train or calibrate")
        if row["label_provenance"].casefold() not in ALLOWED_PROVENANCE:
            raise ValueError("Technical training needs independently reviewed applicability labels")
        if not all(row[field].strip() for field in fields):
            raise ValueError("Training row contains an empty required field")
    return rows


def split_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Hold out entire sources, then reject family and near-template overlap."""
    sources = sorted({row["source"] for row in rows})
    if len(sources) < MIN_SOURCES:
        raise ValueError("Need at least three independent labelled sources for grouped splits")
    random.Random(SEED).shuffle(sources)
    train_sources = set(sources[: max(1, len(sources) - 2)])
    names = {
        source: (
            "train"
            if source in train_sources
            else "calibration"
            if source == sources[-2]
            else "test"
        )
        for source in sources
    }
    splits: dict[str, list[dict[str, str]]] = {key: [] for key in ("train", "calibration", "test")}
    for row in rows:
        splits[names[row["source"]]].append(row)
    family_splits: dict[str, str] = {}
    normalized_splits: dict[str, str] = {}
    for split, items in splits.items():
        if not items:
            raise ValueError(f"Empty {split} split")
        for row in items:
            family = _normalized(row["family"])
            if family in family_splits and family_splits[family] != split:
                raise ValueError("Task family crosses splits")
            family_splits[family] = split
            signature = _normalized(row["stored_question"] + " " + row["incoming_question"])
            if signature in normalized_splits and normalized_splits[signature] != split:
                raise ValueError("Near-duplicate question pair crosses splits")
            normalized_splits[signature] = split
    # Token-overlap template check across splits, bounded by MAX_ROWS.
    token_sets = {
        name: [
            set(_normalized(row["stored_question"] + " " + row["incoming_question"]).split())
            for row in items
        ]
        for name, items in splits.items()
    }
    for left, right in (("train", "calibration"), ("train", "test"), ("calibration", "test")):
        for a in token_sets[left]:
            for b in token_sets[right]:
                if len(a & b) / max(1, len(a | b)) > NEAR_DUPLICATE_THRESHOLD:
                    raise ValueError(f"Near-duplicate template crosses {left}/{right}")
    return splits


def choose_threshold(scored: list[tuple[float, int]]) -> tuple[float, dict]:
    """Select a threshold on calibration only; the untouched test is the gate."""
    if not scored:
        raise ValueError("Empty calibration set")
    for threshold in sorted({score for score, _ in scored}):
        accepted = [label for score, label in scored if score >= threshold]
        wrong = accepted.count(0)
        if wrong or len(accepted) < MIN_ACCEPTS:
            continue
        upper = 1 - 0.05 ** (1 / len(accepted))
        if upper <= TARGET_ERROR_BOUND:
            return threshold, {
                "validated": False,
                "accepted": len(accepted),
                "wrong_accepts": wrong,
                "diagnostic_upper_not_post_selection_valid": upper,
                "method": (
                    "threshold selected on source-held-out calibration; "
                    "test source remains untouched"
                ),
            }
    raise ValueError("Calibration selected reject-all or lacked enough accepted examples")


def train(input_path: Path, output: Path) -> None:  # noqa: PLR0915 - one bounded training lifecycle
    rows = load_rows(input_path)
    splits = split_rows(rows)
    if output.exists():
        raise FileExistsError("Training never overwrites an existing artifact")
    import torch  # noqa: PLC0415 - training dependency loaded only when invoked
    from transformers import (  # noqa: PLC0415 - training dependency loaded only when invoked
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    torch.manual_seed(SEED)
    tokenizer = AutoTokenizer.from_pretrained(
        settings.nli_model, revision=settings.nli_revision, local_files_only=True
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        settings.nli_model,
        revision=settings.nli_revision,
        num_labels=1,
        ignore_mismatched_sizes=True,
        local_files_only=True,
    ).to("cpu")
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5)
    rng = random.Random(SEED)
    for _ in range(EPOCHS):
        epoch = list(splits["train"])
        rng.shuffle(epoch)
        for start in range(0, len(epoch), BATCH_SIZE):
            batch = epoch[start : start + BATCH_SIZE]
            pairs = [
                format_input(row["stored_question"], row["stored_answer"], row["incoming_question"])
                for row in batch
            ]
            encoded = tokenizer(
                [pair[0] for pair in pairs],
                [pair[1] for pair in pairs],
                padding=True,
                truncation=False,
                return_tensors="pt",
            )
            if encoded["input_ids"].shape[1] > model.config.max_position_embeddings:
                raise ValueError("Training input exceeds complete model window")
            labels = torch.tensor([float(row["reuse_ok"]) for row in batch])
            optimizer.zero_grad()
            logits = model(**encoded).logits.reshape(-1)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, labels)
            loss.backward()
            optimizer.step()
    model.eval()

    def score(items: list[dict[str, str]]) -> list[tuple[float, int]]:
        scored = []
        with torch.inference_mode():
            for row in items:
                encoded = tokenizer(
                    *format_input(
                        row["stored_question"], row["stored_answer"], row["incoming_question"]
                    ),
                    truncation=False,
                    return_tensors="pt",
                )
                if encoded["input_ids"].shape[1] > model.config.max_position_embeddings:
                    raise ValueError("Evaluation input exceeds complete model window")
                value = float(torch.sigmoid(model(**encoded).logits.reshape(-1)[0]))
                scored.append((value, int(row["reuse_ok"])))
        return scored

    threshold, calibration = choose_threshold(score(splits["calibration"]))
    test_scores = score(splits["test"])
    test_accepted = [label for value, label in test_scores if value >= threshold]
    wrong_test = test_accepted.count(0)
    test_upper = 1 - 0.05 ** (1 / len(test_accepted)) if test_accepted else 1.0
    if wrong_test or len(test_accepted) < MIN_ACCEPTS or test_upper > TARGET_ERROR_BOUND:
        raise ValueError("Untouched source-held-out test did not validate reuse threshold")
    calibration["validated"] = True
    calibration["test_accepted"] = len(test_accepted)
    calibration["test_one_sided_95pct_upper"] = test_upper
    calibration["test_count"] = len(test_scores)
    calibration["test_valid_reused"] = sum(
        score >= threshold and label == 1 for score, label in test_scores
    )
    calibration["test_invalid_accepted"] = sum(
        score >= threshold and label == 0 for score, label in test_scores
    )
    calibration["test_labels"] = dict(Counter(str(label) for _, label in test_scores))
    output.mkdir(parents=True)
    model.save_pretrained(output, safe_serialization=True)
    tokenizer.save_pretrained(output)
    files = {
        path.name: sha256_file(path)
        for path in output.iterdir()
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = {
        "format_version": FORMAT_VERSION,
        "base_model": settings.nli_model,
        "base_revision": settings.nli_revision,
        "input_sha256": sha256_file(input_path),
        "input_format": "stored-question-and-answer paired with incoming-question",
        "accept_at": threshold,
        "calibration": calibration,
        "split_counts": {name: len(items) for name, items in splits.items()},
        "seed": SEED,
        "epochs": EPOCHS,
        "batch_size": BATCH_SIZE,
        "files": files,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    train(args.input, args.output)
