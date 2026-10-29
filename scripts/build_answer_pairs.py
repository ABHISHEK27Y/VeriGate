"""Mine disjoint NQ-Open factoid pairs with oracle gold-answer-match labels.

Run ``python -m scripts.build_answer_pairs``. The public source and mined text
stay under gitignored data/. No paid provider is called.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import urllib.request
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import numpy as np

from app.cache.accept_model import features
from app.config import get_settings
from app.embeddings import active_backend
from evaluation.gold_answers import normalized_aliases, reuse_ok
from evaluation.reproduce import ROOT, _batch_model

SOURCE_URL = (
    "https://raw.githubusercontent.com/google-research-datasets/natural-questions/"
    "master/nq_open/NQ-open.train.jsonl"
)
DATA = ROOT / "data"
SOURCE = DATA / "NQ-open.train.jsonl"
OUTPUT = DATA / "gold_answer_pairs.tsv"
SEED = 42
MIN_SIMILARITY = 0.55
MAX_QUESTIONS = 10_000
MAX_PAIRS = 1_200
NEIGHBORS = 32
MIN_GROUP = 2
MAX_GROUP = 4
FIELDS = (
    "source_id",
    "stored_query",
    "incoming_query",
    "cached_answer",
    "stored_aliases",
    "incoming_aliases",
    "reuse_ok",
    "label_type",
    "embedding_similarity",
    "hard_negative",
)


@dataclass(frozen=True, slots=True)
class Question:
    source_id: int
    text: str
    answers: tuple[str, ...]
    aliases: frozenset[str]


def _download() -> None:
    if SOURCE.is_file():
        return
    DATA.mkdir(exist_ok=True)
    with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:  # noqa: S310
        SOURCE.write_bytes(response.read())


def _source_questions(path: Path) -> list[Question]:
    questions = []
    seen = set()
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            record = json.loads(line)
            query = str(record["question"]).strip()
            answers = tuple(str(value).strip() for value in record["answer"] if str(value).strip())
            aliases = normalized_aliases(list(answers))
            key = query.casefold()
            if query and aliases and key not in seen:
                questions.append(Question(index, query, answers, aliases))
                seen.add(key)
    return questions


def _sample(questions: list[Question], maximum: int) -> tuple[list[Question], list[list[int]]]:
    """Enrich repeated-answer groups, then mine pairs after embedding."""
    buckets: dict[str, list[int]] = {}
    for index, question in enumerate(questions):
        for answer in question.aliases:
            buckets.setdefault(answer, []).append(index)
    rng = random.Random(SEED)
    keys = sorted(key for key, values in buckets.items() if len(values) >= MIN_GROUP)
    rng.shuffle(keys)
    chosen: dict[int, int] = {}
    groups: list[list[int]] = []
    for key in keys:
        if len(chosen) >= maximum:
            break
        choices = buckets[key].copy()
        rng.shuffle(choices)
        group = []
        for original in choices:
            if original not in chosen and len(chosen) < maximum:
                chosen[original] = len(chosen)
                group.append(chosen[original])
            if len(group) == MAX_GROUP:
                break
        if len(group) >= MIN_GROUP:
            groups.append(group)
    return [questions[index] for index in chosen], groups


def _positive_candidates(
    questions: list[Question], vectors: np.ndarray, groups: list[list[int]]
) -> list[tuple[float, int, int, bool]]:
    candidates = []
    for group in groups:
        for left, right in combinations(group, 2):
            score = float(vectors[left] @ vectors[right])
            if score >= MIN_SIMILARITY and reuse_ok(
                list(questions[left].answers), list(questions[right].answers)
            ):
                candidates.append((score, left, right, False))
    return candidates


def _negative_candidates(
    questions: list[Question], vectors: np.ndarray
) -> list[tuple[float, int, int, bool]]:
    candidates = []
    count = len(questions)
    k = min(NEIGHBORS, count - 1)
    for start in range(0, count, 256):
        similarity = vectors[start : start + 256] @ vectors.T
        for offset, row in enumerate(similarity):
            left = start + offset
            row[left] = -1
            nearest = np.argpartition(row, -k)[-k:]
            for candidate in nearest:
                right = int(candidate)
                if left >= right or row[right] < MIN_SIMILARITY:
                    continue
                if questions[left].aliases & questions[right].aliases:
                    continue
                flags = features(questions[left].text, questions[right].text, float(row[right]), 0)
                hard = bool(flags[3] or flags[5] or flags[6])
                candidates.append((float(row[right]), left, right, hard))
    return candidates


def _choose_disjoint(
    positive: list[tuple[float, int, int, bool]],
    negative: list[tuple[float, int, int, bool]],
    limit: int,
) -> list[tuple[float, int, int, bool, bool]]:
    used: set[int] = set()
    selected: list[tuple[float, int, int, bool, bool]] = []
    for score, left, right, hard in sorted(positive, reverse=True):
        if len(selected) >= limit // 2:
            break
        if left not in used and right not in used:
            selected.append((score, left, right, True, hard))
            used.update((left, right))
    target_negative = len(selected)
    hard_first = sorted(negative, key=lambda row: (row[3], row[0]), reverse=True)
    negative_count = 0
    for score, left, right, hard in hard_first:
        if negative_count >= target_negative:
            break
        if left not in used and right not in used:
            selected.append((score, left, right, False, hard))
            used.update((left, right))
            negative_count += 1
    if not selected or negative_count == 0:
        raise ValueError("No balanced gold-answer candidates survived mining")
    random.Random(SEED).shuffle(selected)
    return selected


def build(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, object]:
    if active_backend() != "minilm":
        raise ValueError("Gold-answer mining requires the pinned MiniLM embedding backend")
    questions, groups = _sample(_source_questions(source), MAX_QUESTIONS)
    model = _batch_model()
    vectors = np.asarray(
        model.encode(
            [question.text for question in questions],
            batch_size=64,
            normalize_embeddings=True,
            show_progress_bar=False,
        ),
        dtype=np.float32,
    )
    positive = _positive_candidates(questions, vectors, groups)
    negative = _negative_candidates(questions, vectors)
    selected = _choose_disjoint(positive, negative, MAX_PAIRS)
    output.parent.mkdir(exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for score, left, right, label, hard in selected:
            first, second = questions[left], questions[right]
            writer.writerow(
                {
                    "source_id": f"nq:{first.source_id}:{second.source_id}",
                    "stored_query": first.text,
                    "incoming_query": second.text,
                    "cached_answer": first.answers[0],
                    "stored_aliases": json.dumps(first.answers, ensure_ascii=False),
                    "incoming_aliases": json.dumps(second.answers, ensure_ascii=False),
                    "reuse_ok": int(label),
                    "label_type": "gold_answer_match",
                    "embedding_similarity": f"{score:.8f}",
                    "hard_negative": int(hard and not label),
                }
            )
    manifest: dict[str, object] = {
        "source": "NQ-open train",
        "source_url": SOURCE_URL,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "derived_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "embedding_model": get_settings().embedding_model,
        "embedding_revision": get_settings().embedding_revision,
        "seed": SEED,
        "minimum_cosine": MIN_SIMILARITY,
        "sampled_questions": len(questions),
        "positive_candidates": len(positive),
        "negative_candidates": len(negative),
        "selected_pairs": len(selected),
        "selected_positive": sum(row[3] for row in selected),
        "selected_negative": sum(not row[3] for row in selected),
        "selected_hard_negative": sum(row[4] for row in selected),
        "label_type": "gold_answer_match",
    }
    output.with_suffix(".provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download", action="store_true", help="Download official NQ-Open train if absent"
    )
    args = parser.parse_args()
    if args.download:
        _download()
    if not SOURCE.is_file():
        raise SystemExit("NQ-Open train missing; run again with --download")
    print(json.dumps(build(), indent=2))


if __name__ == "__main__":
    main()
