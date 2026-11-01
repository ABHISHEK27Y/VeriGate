"""Run two local answer judges on controlled cases and the unlabelled review queue."""

from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path

from scripts.judge_answer_reuse import LocalJudge, Triple, _prompt

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evaluation" / "controlled_answer_cases.json"
QUEUE = ROOT / "data" / "answer_review_directional.tsv"
OUT = ROOT / "data" / "automated_answer_judges.tsv"
SUMMARY = ROOT / "evaluation" / "results" / "automated_judge_validation.json"
NLI_MODEL = "cross-encoder/nli-deberta-v3-xsmall"
NLI_REVISION = "a150876415327c80daeff35ca6f68f5ed8cf5c24"
FLAN_REVISION = "0fc9ddf78a1e988dac52e2dac162b0ede4fd74ab"
NLI_LOW = 0.2
NLI_HIGH = 0.8


def _nli_decisions(rows: list[dict]) -> list[tuple[bool | None, float]]:
    from sentence_transformers import CrossEncoder  # noqa: PLC0415

    model = CrossEncoder(NLI_MODEL, revision=NLI_REVISION, local_files_only=True)
    labels = model.model.config.id2label
    entail = next(int(k) for k, v in labels.items() if "entail" in v.lower())
    prompts = [
        (
            f"The answer to {r['stored']} is {r['answer']}.",
            f"The answer to {r['incoming']} is {r['answer']}.",
        )
        for r in rows
    ]
    predictions = model.predict(prompts, batch_size=16, apply_softmax=True, show_progress_bar=False)
    result = []
    for prediction in predictions:
        score = float(prediction[entail])
        result.append((True if score >= NLI_HIGH else False if score <= NLI_LOW else None, score))
    return result


def run() -> dict:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    with QUEUE.open(newline="", encoding="utf-8") as stream:
        queue = list(csv.DictReader(stream, delimiter="\t"))
    rows = [
        {
            "id": c["id"],
            "split": "controlled",
            "category": c["category"],
            "stored": c["stored"],
            "answer": c["answer"],
            "incoming": c["incoming"],
            "gold": c["valid"],
        }
        for c in cases
    ]
    rows += [
        {
            "id": f"{i}:{r['source_id']}",
            "split": r["review_subset"],
            "category": r["negative_type"],
            "stored": r["stored_query"],
            "answer": r["cached_answer"],
            "incoming": r["incoming_query"],
            "gold": None,
        }
        for i, r in enumerate(queue)
    ]
    triples = [Triple("local", r["id"], r["stored"], r["answer"], r["incoming"]) for r in rows]
    start = time.perf_counter()
    flan = LocalJudge().decide_many(triples)
    flan_seconds = time.perf_counter() - start
    start = time.perf_counter()
    nli = _nli_decisions(rows)
    nli_seconds = time.perf_counter() - start
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as stream:
        fields = (
            "id",
            "split",
            "category",
            "stored",
            "answer",
            "incoming",
            "gold",
            "flan_decision",
            "flan_explanation",
            "flan_prompt",
            "flan_model_revision",
            "nli_decision",
            "nli_explanation",
            "nli_prompt",
            "nli_score",
            "nli_model_revision",
            "agreement",
            "label_type",
        )
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row, triple, first, (second, score) in zip(rows, triples, flan, nli, strict=True):
            writer.writerow(
                {
                    **row,
                    "flan_decision": first,
                    "flan_explanation": "FLAN generated YES/NO; no free-text rationale",
                    "flan_prompt": _prompt(triple),
                    "flan_model_revision": FLAN_REVISION,
                    "nli_decision": second,
                    "nli_explanation": f"answer-hypothesis entailment score={score:.5f}",
                    "nli_prompt": (
                        f"The answer to {row['stored']} is {row['answer']}. => "
                        f"The answer to {row['incoming']} is {row['answer']}."
                    ),
                    "nli_score": score,
                    "nli_model_revision": NLI_REVISION,
                    "agreement": first == second
                    if first is not None and second is not None
                    else "uncertain",
                    "label_type": "controlled_known"
                    if row["split"] == "controlled"
                    else "model_judged",
                }
            )
    known = [i for i, row in enumerate(rows) if row["gold"] is not None]
    summary = {
        "schema_version": "automated-judge-v1",
        "source_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
        "queue_sha256": hashlib.sha256(QUEUE.read_bytes()).hexdigest(),
        "controlled_n": len(known),
        "queue_counts": {s: sum(r["split"] == s for r in rows) for s in ("diagnostic", "random")},
        "raw_output": "data/automated_answer_judges.tsv",
        "run_config": {
            "batch_size": 16,
            "nli_low": 0.2,
            "nli_high": 0.8,
            "flan_model": "google/flan-t5-small",
            "flan_revision": FLAN_REVISION,
            "nli_model": NLI_MODEL,
            "nli_revision": NLI_REVISION,
        },
        "elapsed_seconds": {"flan": flan_seconds, "nli": nli_seconds},
    }
    for name, decisions in (("flan", flan), ("nli", [x[0] for x in nli])):
        tp = sum(decisions[i] is True and rows[i]["gold"] is True for i in known)
        fp = sum(decisions[i] is True and rows[i]["gold"] is False for i in known)
        fn = sum(decisions[i] is not True and rows[i]["gold"] is True for i in known)
        summary[name] = {
            "correct": sum(decisions[i] == rows[i]["gold"] for i in known),
            "abstained": sum(decisions[i] is None for i in known),
            "n": len(known),
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
        }
    summary["queue_disagreements"] = {
        split: sum(
            row["split"] == split and first != second
            for row, first, (second, _) in zip(rows, flan, nli, strict=True)
        )
        for split in ("diagnostic", "random")
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
