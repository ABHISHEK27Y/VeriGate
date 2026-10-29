"""Local, provenance-preserving pair loaders. Public pair labels are not answer labels."""

from __future__ import annotations

import csv
import hashlib
import random
import re
from dataclasses import dataclass
from pathlib import Path

from evaluation import benchmark

_SPACE = re.compile(r"\s+")
_STS_MAX = 5.0
_SUM_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class Pair:
    stored_query: str
    incoming_query: str
    equivalent: bool
    source: str
    source_id: str
    family: str = ""
    cached_answer: str | None = None
    answer_reusable: bool | None = None
    annotation_status: str = "source_pair_label"
    tenant_id: str = ""
    context_version: str = ""
    answer_version: str = ""

    def __post_init__(self) -> None:
        if not self.stored_query.strip() or not self.incoming_query.strip():
            raise ValueError("Queries must be nonempty")
        if self.answer_reusable is not None and self.cached_answer is None:
            raise ValueError("An answer-reuse label requires the actual cached answer")


def smoke() -> list[Pair]:
    """The historical hand fixture; never use it as an independent test set."""
    return [
        Pair(
            a,
            b,
            label,
            "verigate_smoke",
            f"{int(label)}:{index}",
            annotation_status="hand_pair_label",
        )
        for label, pairs in ((True, benchmark.POSITIVES), (False, benchmark.NEGATIVES))
        for index, (a, b) in enumerate(pairs)
    ]


def _load_tsv(  # noqa: PLR0913 - dataset schemas require distinct column names
    path: Path,
    *,
    source: str,
    first: str,
    second: str,
    label: str,
    positive: str = "1",
    threshold: float | None = None,
) -> list[Pair]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {source} input: {path}")
    rows: list[Pair] = []
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        required = {first, second, label}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"{path} lacks columns: {sorted(required)}")
        for index, row in enumerate(reader):
            a, b = (row[first] or "").strip(), (row[second] or "").strip()
            if not a or not b:
                continue
            raw = (row[label] or "").strip()
            try:
                equivalent = float(raw) >= threshold if threshold is not None else raw == positive
            except ValueError:
                continue
            if threshold is None and raw not in {"0", "1"}:
                continue
            rows.append(Pair(a, b, equivalent, source, row.get("id") or str(index)))
    return rows


def qqp(path: Path) -> list[Pair]:
    return _load_tsv(
        path, source="qqp", first="question1", second="question2", label="is_duplicate"
    )


def paws(path: Path) -> list[Pair]:
    return _load_tsv(path, source="paws", first="sentence1", second="sentence2", label="label")


def stsb(path: Path, *, threshold: float = 4.0) -> list[Pair]:
    """STS-B similarity scores >= 4/5 are a documented *proxy* for equivalence."""
    if not 0.0 <= threshold <= _STS_MAX:
        raise ValueError("STS-B threshold must be within its 0..5 scale")
    return _load_tsv(
        path,
        source="stsb",
        first="sentence1",
        second="sentence2",
        label="score",
        threshold=threshold,
    )


def reviewed_answers(path: Path) -> list[Pair]:
    """Load independently resolved answer-reuse labels; leave incomplete rows out."""
    required = {
        "source",
        "source_id",
        "family",
        "stored_query",
        "cached_answer",
        "incoming_query",
        "pair_label",
        "answer_reusable",
        "reason",
        "reviewer_1",
        "reviewer_2",
        "review_status",
        "tenant_id",
        "context_version",
        "answer_version",
    }
    if not path.is_file():
        raise FileNotFoundError(path)
    result: list[Pair] = []
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Answer review file lacks columns: {sorted(required)}")
        for row in reader:
            if row["review_status"] != "resolved_two_reviewers":
                continue
            first, second = row["reviewer_1"].strip(), row["reviewer_2"].strip()
            if not first or not second or first == second:
                raise ValueError("Resolved rows require two distinct reviewers")
            if row["pair_label"] not in {"0", "1"} or row["answer_reusable"] not in {"0", "1"}:
                raise ValueError("Resolved rows require binary pair and answer labels")
            if not row["cached_answer"].strip() or not row["reason"].strip():
                raise ValueError("Resolved rows require the answer and review reason")
            if not all(
                row[key].strip() for key in ("tenant_id", "context_version", "answer_version")
            ):
                raise ValueError("Resolved rows require tenant and context/version metadata")
            result.append(
                Pair(
                    stored_query=row["stored_query"],
                    incoming_query=row["incoming_query"],
                    equivalent=row["pair_label"] == "1",
                    source=row["source"],
                    source_id=row["source_id"],
                    family=row["family"],
                    cached_answer=row["cached_answer"],
                    answer_reusable=row["answer_reusable"] == "1",
                    annotation_status="resolved_two_reviewers",
                    tenant_id=row["tenant_id"],
                    context_version=row["context_version"],
                    answer_version=row["answer_version"],
                )
            )
    return result


def _normalise(query: str) -> str:
    return _SPACE.sub(" ", query.casefold().strip())


def group_split(
    pairs: list[Pair],
    seed: int,
    fractions: tuple[float, float, float, float] = (0.6, 0.15, 0.1, 0.15),
) -> dict[str, list[Pair]]:
    """Keep connected query/family components in one split, even through transitive links."""
    if not pairs:
        raise ValueError("Cannot split an empty dataset")
    if any(x < 0 for x in fractions) or abs(sum(fractions) - 1.0) > _SUM_TOLERANCE:
        raise ValueError("Split fractions must be nonnegative and sum to one")
    parent = list(range(len(pairs)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seen: dict[str, int] = {}
    for index, pair in enumerate(pairs):
        keys = [f"q:{_normalise(pair.stored_query)}", f"q:{_normalise(pair.incoming_query)}"]
        if pair.family:
            keys.append(f"family:{pair.source}:{pair.family}")
        for key in keys:
            if key in seen:
                parent[find(index)] = find(seen[key])
            else:
                seen[key] = index
    components: dict[int, list[Pair]] = {}
    for index, pair in enumerate(pairs):
        components.setdefault(find(index), []).append(pair)
    groups = list(components.values())
    random.Random(seed).shuffle(groups)
    names = ("train", "val", "cal", "test")
    out: dict[str, list[Pair]] = {name: [] for name in names}
    targets = [len(pairs) * x for x in fractions]
    for component in groups:
        candidates = [i for i, target in enumerate(targets) if target > 0]
        chosen = max(candidates, key=lambda i: (targets[i] - len(out[names[i]]), -i))
        out[names[chosen]].extend(component)
    return out


def fingerprint(pairs: list[Pair]) -> str:
    payload = "\n".join(
        f"{p.source}\t{p.source_id}\t{p.stored_query}\t{p.incoming_query}\t{int(p.equivalent)}"
        for p in pairs
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
