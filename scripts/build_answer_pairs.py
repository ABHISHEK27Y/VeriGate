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
import re
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.embeddings import active_backend, tokenize
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
MAX_QUESTIONS = 40_000
MAX_PAIRS = 12_000
MIN_PAIRS = 10_000
MIN_GROUP = 2
MAX_GROUP = 4
MINING_VERSION = "nq-structured-v2"
MIN_QUERY_TOKENS = 4
MIN_SHARED_PREFIX = 2
MIN_CONTEXT_PREFIX = 3
MAX_SWAP_TOKENS = 4
MAX_NEGATIVE_QUERY_USES = 2
LSH_TABLES = 4
LSH_BITS = 8
LSH_NEIGHBORS = 32
MIN_CONTENT_JACCARD = 0.3
PREFIX_CANDIDATES = 100
_RELATIONS = {
    "directed",
    "wrote",
    "produced",
    "created",
    "sang",
    "composed",
    "invented",
    "founded",
    "painted",
    "designed",
    "played",
    "portrayed",
}
_CONTENT_STOP = {
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "is",
    "was",
    "were",
    "are",
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "did",
    "does",
    "do",
    "to",
    "for",
    "with",
    "which",
}
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_ATTRIBUTE = re.compile(
    r"^who (directed|wrote|produced|created|sang|composed|invented|founded|painted|designed) (.+)$"
)
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
    "negative_type",
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
) -> list[tuple[float, int, int, str]]:
    candidates = []
    for group in groups:
        for left, right in combinations(group, 2):
            score = float(vectors[left] @ vectors[right])
            if score >= MIN_SIMILARITY and reuse_ok(
                list(questions[left].answers), list(questions[right].answers)
            ):
                candidates.append((score, left, right, "positive"))
    return candidates


def _entity_span_swap(first: str, second: str) -> bool:
    """Conservative lexical entity-slot proxy, not named-entity recognition."""
    left, right = first.lower().split(), second.lower().split()
    if (
        len(left) < MIN_QUERY_TOKENS
        or len(right) < MIN_QUERY_TOKENS
        or left[:MIN_SHARED_PREFIX] != right[:MIN_SHARED_PREFIX]
    ):
        return False
    if _NUMBER.findall(first) != _NUMBER.findall(second):
        return False
    prefix = 0
    while prefix < min(len(left), len(right)) and left[prefix] == right[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(left), len(right)) - prefix and left[-suffix - 1] == right[-suffix - 1]:
        suffix += 1
    left_span, right_span = len(left) - prefix - suffix, len(right) - prefix - suffix
    relation_prefix = left[1] in _RELATIONS
    return (
        prefix >= MIN_SHARED_PREFIX
        and 1 <= left_span <= (MAX_SWAP_TOKENS * 2 if relation_prefix else MAX_SWAP_TOKENS)
        and 1 <= right_span <= (MAX_SWAP_TOKENS * 2 if relation_prefix else MAX_SWAP_TOKENS)
        and (relation_prefix or prefix >= MIN_CONTEXT_PREFIX or suffix > 0)
    )


def _negative_candidates(  # noqa: PLR0912, PLR0915 - strategies share a dedup index
    questions: list[Question], vectors: np.ndarray
) -> list[tuple[float, int, int, str]]:
    """Construct typed negatives before checking embedding similarity."""
    candidates: dict[tuple[int, int], tuple[float, int, int, str]] = {}

    def add(left: int, right: int, kind: str) -> None:
        left, right = sorted((left, right))
        if left == right or questions[left].aliases & questions[right].aliases:
            return
        score = float(vectors[left] @ vectors[right])
        if score < MIN_SIMILARITY:
            return
        key = (left, right)
        priority = {
            "lexical_semantic": 0,
            "entity_span_swap": 1,
            "number_swap": 2,
            "attribute_swap": 3,
        }
        previous = candidates.get(key)
        if previous is None or priority[kind] > priority[previous[3]]:
            candidates[key] = (score, left, right, kind)

    numbers: dict[str, list[int]] = defaultdict(list)
    attributes: dict[str, list[tuple[int, str]]] = defaultdict(list)
    prefixes: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, question in enumerate(questions):
        text = question.text.lower()
        if _NUMBER.search(text):
            numbers[_NUMBER.sub("<number>", text)].append(index)
        if match := _ATTRIBUTE.match(text):
            attributes[match.group(2)].append((index, match.group(1)))
        tokens = text.split()
        if len(tokens) >= MIN_QUERY_TOKENS:
            prefixes[(tokens[0], tokens[1])].append(index)

    for number_group in numbers.values():
        for left, right in combinations(number_group, 2):
            if _NUMBER.findall(questions[left].text) != _NUMBER.findall(questions[right].text):
                add(left, right, "number_swap")
    for attribute_group in attributes.values():
        for (left, relation), (right, other_relation) in combinations(attribute_group, 2):
            if relation != other_relation:
                add(left, right, "attribute_swap")

    rng = random.Random(SEED)
    for prefix_group in prefixes.values():
        if len(prefix_group) < MIN_GROUP:
            continue
        # Bounded lexical candidates, independent of MiniLM neighbour ranking.
        for left in prefix_group:
            pool = rng.sample(prefix_group, min(len(prefix_group), PREFIX_CANDIDATES))
            for right in pool:
                if left < right and _entity_span_swap(questions[left].text, questions[right].text):
                    add(left, right, "entity_span_swap")

    # Multi-table random-hyperplane buckets recover high-similarity neighbours
    # without a quadratic all-pairs scan. Require independent content-token
    # overlap as well as different reference answers; cosine alone never labels.
    content = [set(tokenize(q.text)) - _CONTENT_STOP for q in questions]
    generator = np.random.default_rng(SEED)
    for _ in range(LSH_TABLES):
        planes = generator.normal(size=(vectors.shape[1], LSH_BITS)).astype(np.float32)
        bits = (vectors @ planes >= 0).astype(np.uint8)
        codes = bits @ (1 << np.arange(LSH_BITS, dtype=np.uint8))
        buckets: dict[int, list[int]] = defaultdict(list)
        for index, code in enumerate(codes):
            buckets[int(code)].append(index)
        for group in buckets.values():
            if len(group) < MIN_GROUP:
                continue
            matrix = vectors[group] @ vectors[group].T
            for offset, row in enumerate(matrix):
                count = min(LSH_NEIGHBORS + 1, len(group))
                near = np.argpartition(row, -count)[-count:]
                left = group[offset]
                for position in near:
                    right = group[int(position)]
                    if left >= right or row[position] < MIN_SIMILARITY:
                        continue
                    shared = content[left] & content[right]
                    union = content[left] | content[right]
                    if (
                        len(shared) >= MIN_SHARED_PREFIX
                        and len(shared) / len(union) >= MIN_CONTENT_JACCARD
                    ):
                        add(left, right, "lexical_semantic")
    return list(candidates.values())


def _choose_pairs(
    positive: list[tuple[float, int, int, str]],
    negative: list[tuple[float, int, int, str]],
    limit: int,
    *,
    minimum: int = MIN_PAIRS,
) -> list[tuple[float, int, int, bool, str]]:
    used: set[int] = set()
    positive_nodes: set[int] = set()
    selected: list[tuple[float, int, int, bool, str]] = []
    for score, left, right, _ in sorted(positive, reverse=True):
        if len(selected) >= limit // 2:
            break
        if left not in used and right not in used:
            selected.append((score, left, right, True, "positive"))
            used.update((left, right))
            positive_nodes.update((left, right))
    target_negative = limit - len(selected)
    # Prioritize the rarer explicit relations; do not rank all negatives by cosine.
    priority = {
        "attribute_swap": 3,
        "number_swap": 2,
        "entity_span_swap": 1,
        "lexical_semantic": 0,
    }
    hard_first = sorted(negative, key=lambda row: (priority[row[3]], row[0]), reverse=True)
    negative_count = 0
    selected_negative_edges: set[tuple[int, int]] = set()
    negative_usage: dict[int, int] = defaultdict(int)
    for score, left, right, kind in hard_first:
        if negative_count >= target_negative:
            break
        if left not in used and right not in used:
            selected.append((score, left, right, False, kind))
            used.update((left, right))
            selected_negative_edges.add((left, right))
            negative_usage[left] += 1
            negative_usage[right] += 1
            negative_count += 1
    # One extra use of a negative question allows a larger corpus while
    # group_split keeps every connected question component in one split.
    for score, left, right, kind in hard_first:
        if negative_count >= target_negative:
            break
        if (
            left in positive_nodes
            or right in positive_nodes
            or (left, right) in selected_negative_edges
            or negative_usage[left] >= MAX_NEGATIVE_QUERY_USES
            or negative_usage[right] >= MAX_NEGATIVE_QUERY_USES
        ):
            continue
        selected.append((score, left, right, False, kind))
        selected_negative_edges.add((left, right))
        negative_usage[left] += 1
        negative_usage[right] += 1
        negative_count += 1
    if len(selected) < minimum:
        raise ValueError(
            f"Only {len(selected)} disjoint pairs survived; need {minimum}; "
            f"positive candidates={len(positive)}, negative candidates={len(negative)}, "
            f"selected positives={sum(row[3] for row in selected)}"
        )
    random.Random(SEED).shuffle(selected)
    return selected


def build(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, object]:
    if active_backend() != "minilm":
        raise ValueError("Gold-answer mining requires the pinned MiniLM embedding backend")
    questions, groups = _sample(_source_questions(source), MAX_QUESTIONS)
    digest = hashlib.sha256(
        (get_settings().embedding_revision + "\n" + "\n".join(q.text for q in questions)).encode()
    ).hexdigest()
    vector_cache = DATA / f"nq_miner_vectors_{digest[:16]}.npz"
    if vector_cache.is_file():
        with np.load(vector_cache) as saved:
            vectors = np.asarray(saved["vectors"], dtype=np.float32)
    else:
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
        np.savez_compressed(vector_cache, vectors=vectors)
    positive = _positive_candidates(questions, vectors, groups)
    negative = _negative_candidates(questions, vectors)
    selected = _choose_pairs(positive, negative, MAX_PAIRS)
    output.parent.mkdir(exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for score, left, right, label, kind in selected:
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
                    "hard_negative": int(not label),
                    "negative_type": kind if not label else "",
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
        "mining_version": MINING_VERSION,
        "minimum_cosine": MIN_SIMILARITY,
        "sampled_questions": len(questions),
        "positive_candidates": len(positive),
        "negative_candidates": len(negative),
        "selected_pairs": len(selected),
        "selected_positive": sum(row[3] for row in selected),
        "selected_negative": sum(not row[3] for row in selected),
        "selected_hard_negative": sum(not row[3] for row in selected),
        "selected_negative_types": {
            kind: sum(row[4] == kind for row in selected)
            for kind in ("attribute_swap", "number_swap", "entity_span_swap", "lexical_semantic")
        },
        "label_type": "gold_answer_match",
    }
    output.with_suffix(".provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    aggregate = ROOT / "evaluation" / "results" / "gold_mining.csv"
    aggregate.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "mining_version": MINING_VERSION,
        "source_sha256": manifest["source_sha256"],
        "derived_sha256": manifest["derived_sha256"],
        "sampled_questions": len(questions),
        "positive_candidates": len(positive),
        "negative_candidates": len(negative),
        "selected_pairs": len(selected),
        "selected_positive": sum(item[3] for item in selected),
        "selected_negative": sum(not item[3] for item in selected),
        **{
            kind: sum(item[4] == kind for item in selected)
            for kind in ("attribute_swap", "number_swap", "entity_span_swap", "lexical_semantic")
        },
    }
    with aggregate.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=row.keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
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
