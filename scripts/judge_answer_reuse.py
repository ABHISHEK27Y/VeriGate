"""Validate a pinned local judge, then label only previously unlabelled triples.

The judge's YES/NO is a model opinion, never gold truth. Raw queue/shadow text
and per-row model judgements remain in gitignored data/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np

from app.cache.namespace import namespace
from app.config import get_settings
from evaluation.datasets import group_split
from evaluation.gold_answers import load_pairs
from evaluation.reproduce import ROOT

MODEL = "google/flan-t5-small"
REVISION = "0fc9ddf78a1e988dac52e2dac162b0ede4fd74ab"
PROMPT_VERSION = "triple-yes-no-v1"
GOLD = ROOT / "data" / "gold_answer_pairs.tsv"
QUEUE = ROOT / "data" / "answer_review.tsv"
OUTPUT = ROOT / "data" / "model_judged.tsv"
RESULTS = ROOT / "evaluation" / "results"
BOOTSTRAPS = 1000


@dataclass(frozen=True, slots=True)
class Triple:
    source: str
    source_id: str
    cached_query: str
    cached_answer: str
    new_query: str


def _prompt(triple: Triple) -> str:
    return (
        "Can the cached answer correctly answer the new question? "
        "Reply with only YES or NO.\n"
        f"Cached question: {triple.cached_query}\n"
        f"Cached answer: {triple.cached_answer}\n"
        f"New question: {triple.new_query}\n"
        "Decision:"
    )


def _parse_answer(text: str) -> bool | None:
    token = text.strip().split(maxsplit=1)[0].strip(".!,:").casefold() if text.strip() else ""
    if token == "yes":
        return True
    if token == "no":
        return False
    return None


class LocalJudge:
    def __init__(self) -> None:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # noqa: PLC0415

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(MODEL, revision=REVISION)
        self.model.eval()

    def decide_many(self, triples: list[Triple]) -> list[bool | None]:
        import torch  # noqa: PLC0415 - local research model only

        decisions: list[bool | None] = []
        for start in range(0, len(triples), 16):
            batch = [_prompt(triple) for triple in triples[start : start + 16]]
            encoded = self.tokenizer(
                batch, return_tensors="pt", padding=True, truncation=True, max_length=256
            )
            with torch.no_grad():
                tokens = self.model.generate(**encoded, max_new_tokens=4, do_sample=False)
            decisions.extend(
                _parse_answer(text)
                for text in self.tokenizer.batch_decode(tokens, skip_special_tokens=True)
            )
        return decisions


def _scores(gold: list[bool], predicted: list[bool | None]) -> dict[str, float | None]:
    if not gold or len(gold) != len(predicted):
        raise ValueError("Aligned nonempty gold and judge predictions are required")
    # Abstentions count as NO for all primary scores; report their rate too.
    yes = [value is True for value in predicted]
    true_positive = sum(actual and guess for actual, guess in zip(gold, yes, strict=True))
    predicted_positive = sum(yes)
    gold_positive = sum(gold)
    accuracy = sum(actual == guess for actual, guess in zip(gold, yes, strict=True)) / len(gold)
    p_gold, p_predicted = gold_positive / len(gold), predicted_positive / len(gold)
    chance = p_gold * p_predicted + (1 - p_gold) * (1 - p_predicted)
    return {
        "accuracy": accuracy,
        "precision": true_positive / predicted_positive if predicted_positive else None,
        "recall": true_positive / gold_positive if gold_positive else None,
        "cohen_kappa": (accuracy - chance) / (1 - chance) if chance < 1 else None,
        "abstain_rate": sum(value is None for value in predicted) / len(gold),
    }


def _intervals(
    gold: list[bool], predicted: list[bool | None]
) -> dict[str, tuple[float | None, float | None]]:
    rng = random.Random(11)
    samples: dict[str, list[float]] = {key: [] for key in _scores(gold, predicted)}
    for _ in range(BOOTSTRAPS):
        indices = [rng.randrange(len(gold)) for _ in gold]
        measurement = _scores([gold[i] for i in indices], [predicted[i] for i in indices])
        for key, value in measurement.items():
            if value is not None:
                samples[key].append(value)
    return {
        key: (
            (float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975)))
            if values
            else (None, None)
        )
        for key, values in samples.items()
    }


def _queue_triples(path: Path) -> tuple[list[Triple], int]:
    if not path.is_file():
        return [], 0
    eligible = []
    skipped_blank = 0
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        required = {"source", "source_id", "stored_query", "cached_answer", "incoming_query"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Review queue lacks judge input fields")
        for row in reader:
            if row.get("answer_reusable", "").strip():
                continue  # already labelled; never relabel or mix
            answer = row["cached_answer"].strip()
            if not answer:
                skipped_blank += 1
                continue
            eligible.append(
                Triple(
                    row["source"],
                    row["source_id"],
                    row["stored_query"],
                    answer,
                    row["incoming_query"],
                )
            )
    return eligible, skipped_blank


def _shadow_triples(tenant: str) -> list[Triple]:
    import redis  # noqa: PLC0415 - optional live shadow source

    url = get_settings().redis_url
    if not url:
        raise ValueError("--shadow-tenant requires REDIS_URL; in-memory Redis is not shared")
    client = redis.Redis.from_url(url, decode_responses=True)
    try:
        records = cast(list[str], client.lrange(f"{namespace()}:shadow:review:{tenant}", 0, -1))
    finally:
        client.close()
    triples = []
    for raw in records:
        row = json.loads(raw)
        if row.get("label") is not None or row.get("review_status") != "unreviewed":
            continue
        if not all(row.get(key) for key in ("cached_query", "cached_answer", "prompt")):
            continue  # older records lack cached_query; do not infer it
        triples.append(
            Triple(
                "shadow",
                row["id"],
                row["cached_query"],
                row["cached_answer"],
                row["prompt"],
            )
        )
    return triples


def _validate(judge: LocalJudge) -> dict[str, Any]:
    gold, _ = load_pairs(GOLD)
    test = group_split(gold, 11)["test"]
    triples = [
        Triple(
            "nq_open",
            pair.source_id,
            pair.stored_query,
            pair.cached_answer or "",
            pair.incoming_query,
        )
        for pair in test
    ]
    predicted = judge.decide_many(triples)
    labels = [bool(pair.answer_reusable) for pair in test]
    scores, intervals = _scores(labels, predicted), _intervals(labels, predicted)
    row: dict[str, Any] = {
        "model": MODEL,
        "revision": REVISION,
        "prompt_version": PROMPT_VERSION,
        "validation_source": "nq_open_grouped_test_seed_11",
        "n": len(test),
        "gold_positive": sum(labels),
        "predicted_positive": sum(value is True for value in predicted),
        "abstentions": sum(value is None for value in predicted),
        "label_type": "gold_answer_match",
    }
    for key, value in scores.items():
        row[key] = value
        row[f"{key}_ci_low"], row[f"{key}_ci_high"] = intervals[key]
    with (RESULTS / "judge_validation.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=row.keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    return row


def run(*, shadow_tenant: str | None = None, force: bool = False) -> dict[str, Any]:
    RESULTS.mkdir(exist_ok=True)
    judge = LocalJudge()
    validation = _validate(judge)
    queue, skipped_blank = _queue_triples(QUEUE)
    shadow = _shadow_triples(shadow_tenant) if shadow_tenant else []
    unlabelled = queue + shadow
    if unlabelled and OUTPUT.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite model judgements: {OUTPUT}")
    judged_count = abstained_count = 0
    if unlabelled:
        decisions = judge.decide_many(unlabelled)
        judged_count = sum(decision is not None for decision in decisions)
        abstained_count = len(decisions) - judged_count
        with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
            fields = (
                "source",
                "source_id",
                "cached_query",
                "cached_answer",
                "new_query",
                "reuse_ok",
                "judge_abstained",
                "label_type",
                "model_revision",
            )
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for triple, decision in zip(unlabelled, decisions, strict=True):
                writer.writerow(
                    {
                        "source": triple.source,
                        "source_id": triple.source_id,
                        "cached_query": triple.cached_query,
                        "cached_answer": triple.cached_answer,
                        "new_query": triple.new_query,
                        "reuse_ok": "" if decision is None else int(decision),
                        "judge_abstained": int(decision is None),
                        "label_type": "model_judged",
                        "model_revision": REVISION,
                    }
                )
    manifest = {
        "model": MODEL,
        "revision": REVISION,
        "prompt_version": PROMPT_VERSION,
        "validation_gold_sha256": hashlib.sha256(GOLD.read_bytes()).hexdigest(),
        "validation_n": validation["n"],
        "queue_blank_answers_skipped": skipped_blank,
        "queue_eligible": len(queue),
        "shadow_eligible": len(shadow),
        "model_judged_count": judged_count,
        "model_abstained_count": abstained_count,
        "label_type_for_unlabelled": "model_judged",
        "raw_output": "data/model_judged.tsv" if unlabelled else None,
    }
    (RESULTS / "judge_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shadow-tenant", help="Read unreviewed records from this Redis tenant")
    parser.add_argument("--force", action="store_true", help="Overwrite local model_judged.tsv")
    args = parser.parse_args()
    print(json.dumps(run(shadow_tenant=args.shadow_tenant, force=args.force), indent=2))


if __name__ == "__main__":
    main()
