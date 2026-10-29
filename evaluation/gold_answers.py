"""Oracle factoid-answer matching for mined NQ-Open question pairs.

This is a gold-string proxy, not a judgement of a generated LLM answer.
"""

from __future__ import annotations

import csv
import json
import re
import string
from pathlib import Path

from evaluation.datasets import Pair

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_SPACES = re.compile(r"\s+")
_PUNCTUATION = str.maketrans("", "", string.punctuation)
_YEAR = re.compile(r"\b(?:1[0-9]{3}|20[0-9]{2})\b")
_MONTHS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}
_NAME_EXCLUDE = _MONTHS | {"the", "and", "of", "in", "at", "on", "a", "an"}
_MAX_DAY = 31
_MIN_NAME_PARTS = 2


def normalize_answer(answer: str) -> str:
    lowered = answer.casefold().translate(_PUNCTUATION)
    return _SPACES.sub(" ", _ARTICLES.sub(" ", lowered)).strip()


def normalized_aliases(answers: list[str]) -> frozenset[str]:
    return frozenset(value for answer in answers if (value := normalize_answer(answer)))


def reuse_ok(first: list[str], second: list[str]) -> bool:
    left, right = normalized_aliases(first), normalized_aliases(second)
    return bool(left and right and left.intersection(right))


def _name_parts(answer: str) -> set[str]:
    parts = re.findall(r"\b[A-Z][a-z]{2,}\b", answer)
    return {part.casefold() for part in parts if part.casefold() not in _NAME_EXCLUDE}


def _date_parts(answer: str) -> tuple[set[str], set[str], set[str]]:
    normalized = answer.casefold()
    words = set(re.findall(r"[a-z]+", normalized))
    days = {
        number for number in re.findall(r"\b\d{1,2}\b", normalized) if 1 <= int(number) <= _MAX_DAY
    }
    return set(_YEAR.findall(normalized)), words & _MONTHS, days


def lenient_reuse_ok(first: list[str], second: list[str]) -> bool:
    """Broad alias-overlap proxy; intentionally separate from strict matching."""
    if reuse_ok(first, second):
        return True
    for left in first:
        left_tokens = set(normalize_answer(left).split())
        left_years, left_months, left_days = _date_parts(left)
        left_names = _name_parts(left)
        for right in second:
            right_tokens = set(normalize_answer(right).split())
            if (
                left_tokens
                and right_tokens
                and (left_tokens <= right_tokens or right_tokens <= left_tokens)
            ):
                return True
            right_years, right_months, right_days = _date_parts(right)
            if left_years & right_years:
                return True
            if (
                left_months & right_months
                and left_days & right_days
                and not (left_years and right_years and not left_years & right_years)
            ):
                return True
            right_names = _name_parts(right)
            if (
                len(left_names) >= _MIN_NAME_PARTS
                and len(right_names) >= _MIN_NAME_PARTS
                and left_names & right_names
            ):
                return True
    return False


def load_pairs(path: Path) -> tuple[list[Pair], dict[str, frozenset[str]]]:
    """Load gold-labelled pairs and each question's reference-answer aliases."""
    required = {
        "source_id",
        "stored_query",
        "incoming_query",
        "cached_answer",
        "stored_aliases",
        "incoming_aliases",
        "reuse_ok",
        "label_type",
    }
    pairs: list[Pair] = []
    aliases: dict[str, frozenset[str]] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Gold pair file lacks columns: {sorted(required)}")
        for row in reader:
            if row["label_type"] != "gold_answer_match" or row["reuse_ok"] not in {"0", "1"}:
                raise ValueError("Invalid gold-answer label")
            first, second = json.loads(row["stored_aliases"]), json.loads(row["incoming_aliases"])
            if not isinstance(first, list) or not isinstance(second, list):
                raise TypeError("Gold aliases must be lists")
            first_set, second_set = normalized_aliases(first), normalized_aliases(second)
            if (
                not first_set
                or not second_set
                or normalize_answer(row["cached_answer"]) not in first_set
            ):
                raise ValueError("Gold-answer pairs require nonempty answers")
            if (row["reuse_ok"] == "1") != bool(first_set & second_set):
                raise ValueError("Gold-answer match label disagrees with aliases")
            for query, values in (
                (row["stored_query"], first_set),
                (row["incoming_query"], second_set),
            ):
                if query in aliases and aliases[query] != values:
                    raise ValueError("One question has inconsistent gold aliases")
                aliases[query] = values
            pairs.append(
                Pair(
                    stored_query=row["stored_query"],
                    incoming_query=row["incoming_query"],
                    equivalent=row["reuse_ok"] == "1",
                    source="nq_open",
                    source_id=row["source_id"],
                    cached_answer=row["cached_answer"],
                    answer_reusable=row["reuse_ok"] == "1",
                    annotation_status="gold_answer_match",
                )
            )
    if not pairs:
        raise ValueError("Gold-answer pair file is empty")
    return pairs, aliases
