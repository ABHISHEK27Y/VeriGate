"""Freeze and run a new-entity, four-domain HTTP comparison for the subject guard.

The NQ-Open references are authored controls, not independently reviewed labels.
Run build before run. Never edit a built directory; choose a new run ID instead.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

from app.cache.subject_identity import named_work
from scripts.stress_semantic_http import POLICY, ROOT, SOURCE, digest, run_one, write_csv

SEED = 43627
# Curated NQ-Open train source lines. Titles and references are checked against
# those lines during build, before either policy is run.
SELECTED = {
    "song": (80810, 77265, 41834, 65575, 6780, 86662, 5426, 47546, 29837, 61490),
    "book": (4163, 4992, 5155, 7266, 9827, 15375, 16351, 45670, 50807, 54044),
    "film": (19218, 61100, 78590, 78885),
    "poem": (2990, 5368, 34213, 43040, 76896, 49068),
}
SELECTED_V2 = {
    "song": (24243, 978, 49679, 73140, 85266, 796, 46703, 82921),
    "book": (73656, 82259, 57207, 43991, 45275, 34660, 37341, 65626),
    "film": (2786, 19989, 61503),
    "poem": (740, 39723, 44080, 61180, 80212, 82560),
}
TITLE_OVERRIDES = {
    2786: "the piano",
    19989: "thank you for your service",
    61503: "death in the west",
}
PREFIX = {
    "song": "who wrote the song ",
    "book": "who wrote the book ",
    "film": "who directed the film ",
    "poem": "who wrote the poem ",
}
SOURCE_URL = "https://github.com/google-research-datasets/natural-questions/tree/master/nq_open"
OLD = ROOT / "evaluation/runs/nq_song_stress_20261030_v3/workload.csv"


def source_rows(selected: dict[str, tuple[int, ...]]) -> dict[int, dict]:
    wanted = {line for lines in selected.values() for line in lines}
    found = {}
    with SOURCE.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if number in wanted:
                found[number] = json.loads(line)
    if set(found) != wanted:
        raise ValueError("Selected NQ source lines are missing")
    return found


def _title(question: str, kind: str) -> str:
    lower = question.casefold().strip()
    prefix = PREFIX[kind]
    if kind == "film" and lower.startswith("who directed the movie "):
        prefix = "who directed the movie "
    if kind == "book" and lower.startswith("who wrote the novel "):
        prefix = "who wrote the novel "
    if not lower.startswith(prefix):
        raise ValueError(f"Unexpected source question: {question}")
    return question.strip()[len(prefix) :].strip().strip("'\"?")


def build(output: Path) -> None:  # noqa: PLR0912 - validation and frozen input construction
    if output.exists():
        raise FileExistsError(output)
    selected = SELECTED_V2 if output.name.endswith("_v2") else SELECTED
    source = source_rows(selected)
    old_subjects = {
        named_work(row["question"])
        for row in csv.DictReader(OLD.open(encoding="utf-8", newline=""))
    }
    families = []
    for kind, lines in selected.items():
        group = []
        for line in lines:
            record = source[line]
            if len(record["answer"]) != 1:
                raise ValueError(f"Ambiguous source answers at line {line}")
            title = TITLE_OVERRIDES.get(line) or _title(record["question"], kind)
            if line in TITLE_OVERRIDES and title not in record["question"].casefold():
                raise ValueError(f"Title override absent from NQ question at line {line}")
            answer = record["answer"][0].strip()
            subject = named_work(f"Who wrote the {kind} {title}?")
            if not subject or subject in old_subjects:
                raise ValueError(f"Old or unparseable entity at line {line}")
            group.append((line, title, answer))
        if len({answer.casefold() for _, _, answer in group}) != len(group):
            raise ValueError(f"Repeated answer within {kind} domain")
        for index, (line, title, answer) in enumerate(group):
            other_line, other_title, other_answer = group[(index + 1) % len(group)]
            families.append((kind, line, title, answer, other_line, other_title, other_answer))

    rows = []
    answers: dict[str, str] = {}
    for index, (kind, line, title, answer, other_line, other_title, other_answer) in enumerate(
        families
    ):
        family = f"{kind}-{index:03d}"
        verb = "directed" if kind == "film" else "wrote"
        role = "director" if kind == "film" else "writer"
        question_forms = (
            ("original", f"Who {verb} the {kind} {title}?", answer, line, "source-based wording"),
            (
                "paraphrase_1",
                f"Name the {role} of the {kind} {title}.",
                answer,
                line,
                "authored template",
            ),
            (
                "paraphrase_2",
                f"For the {kind} {title}, who {verb} it?",
                answer,
                line,
                "authored fronted template",
            ),
            (
                "hard_negative",
                f"For the {kind} {other_title}, name its {role}.",
                other_answer,
                other_line,
                "authored entity swap",
            ),
        )
        for form, question, reference, source_line, transformation in question_forms:
            if question in answers and answers[question] != reference:
                raise ValueError("Conflicting controlled answers")
            answers[question] = reference
            rows.append(
                {
                    "id": f"{family}:{form}",
                    "family_id": family,
                    "kind": form,
                    "domain": kind,
                    "question": question,
                    "reference_answer": reference,
                    "family_cached_answer": answer,
                    "family_answer_reusable": form != "hard_negative",
                    "contrasts_with": f"{family}:original" if form == "hard_negative" else "",
                    "source_line": source_line,
                    "source_url": SOURCE_URL,
                    "evidence": f"NQ-Open train answer at line {source_line}",
                    "transformation": transformation,
                    "label_status": "authored_control",
                    "uncertainty": (
                        "NQ short reference may omit aliases/co-creators; no independent review"
                    ),
                }
            )
    expected_requests = sum(map(len, selected.values())) * 4
    if len(rows) != expected_requests or len(answers) != expected_requests:
        raise ValueError("Expected four unique questions per family")
    random.Random(SEED).shuffle(rows)
    positions: dict[str, list[int]] = defaultdict(list)
    for position, row in enumerate(rows, 1):
        row["position"] = position
        positions[row["family_id"]].append(position)
    for row in rows:
        earlier = [p for p in positions[row["family_id"]] if p < row["position"]]
        row["distance_from_previous_family"] = row["position"] - max(earlier) if earlier else ""
    output.mkdir(parents=True)
    write_csv(output / "workload.csv", rows)
    (output / "provider_answers.json").write_text(
        json.dumps(answers, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    freeze = {
        "seed": SEED,
        "source": SOURCE_URL,
        "source_license": "CC BY-SA 3.0",
        "source_sha256": digest(SOURCE),
        "old_workload_sha256": digest(OLD),
        "selected_source_lines": selected,
        "families": len(families),
        "requests": len(rows),
        "policy_sha256": digest(POLICY),
        "policy_artifact": POLICY.relative_to(ROOT).as_posix(),
        "comparison": {"unchanged": False, "guarded": True},
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "nli_model": "cross-encoder/nli-deberta-v3-xsmall",
        "nli_revision": "a150876415327c80daeff35ca6f68f5ed8cf5c24",
        "settings": {
            mode: {"cache_ttl_sec": 86400, "max_cache_entries_per_tenant": 256}
            for mode in ("unchanged", "guarded")
        },
        "workload_sha256": digest(output / "workload.csv"),
        "provider_answers_sha256": digest(output / "provider_answers.json"),
        "label_limit": "Authored transformations of NQ references; no independent review.",
    }
    (output / "freeze.json").write_text(json.dumps(freeze, indent=2), encoding="utf-8")
    (output / "DATA_LICENSE.md").write_text(
        "NQ-Open train source questions and short answers: CC BY-SA 3.0. "
        "Derived questions are authored transformations. Source lines and URL are "
        "recorded in workload.csv. No independently reviewed answer labels.\n",
        encoding="utf-8",
    )


async def run(output: Path) -> None:
    freeze = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    for path, expected in (
        (output / "workload.csv", freeze["workload_sha256"]),
        (output / "provider_answers.json", freeze["provider_answers_sha256"]),
        (POLICY, freeze["policy_sha256"]),
        (OLD, freeze["old_workload_sha256"]),
    ):
        if digest(path) != expected:
            raise ValueError(f"Frozen input changed: {path}")
    rows = list(csv.DictReader((output / "workload.csv").open(encoding="utf-8", newline="")))
    answers = json.loads((output / "provider_answers.json").read_text(encoding="utf-8"))
    original = os.environ.get("ANSWER_POLICY_SUBJECT_GUARD")
    try:
        for mode, guard in freeze["comparison"].items():
            directory = output / f"answer_aware_{mode}"
            if directory.exists():
                raise FileExistsError(directory)
            os.environ["ANSWER_POLICY_SUBJECT_GUARD"] = str(guard).lower()
            summary = await run_one(output, "answer_aware", mode, rows, answers, freeze)
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["config"]["ANSWER_POLICY_SUBJECT_GUARD"] = str(guard).lower()
            manifest["runner_sha256"] = digest(Path(__file__))
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(json.dumps(summary), flush=True)
    finally:
        if original is None:
            os.environ.pop("ANSWER_POLICY_SUBJECT_GUARD", None)
        else:
            os.environ["ANSWER_POLICY_SUBJECT_GUARD"] = original


def analyze(output: Path) -> None:
    freeze = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    summaries = []
    for mode in freeze["comparison"]:
        directory = output / f"answer_aware_{mode}"
        rows = list(csv.DictReader((directory / "requests.csv").open(encoding="utf-8", newline="")))
        if len(rows) != freeze["requests"]:
            raise ValueError("Incomplete HTTP run")
        counts = Counter(row["outcome"] for row in rows)
        seen = set()
        potential = 0
        for row in rows:
            potential += row["reference_answer"] in seen
            seen.add(row["reference_answer"])
        summaries.append(
            {
                "mode": mode,
                "requests": len(rows),
                "completed": sum(row["http_status"] == "200" for row in rows),
                "reference_matching_hits": counts["correct_hit"],
                "suspected_wrong_hits": counts["incorrect_acceptance"],
                "verifier_false_rejections": counts["verifier_false_rejection"],
                "live_opportunities": sum(row["suitable_answer_present"] == "True" for row in rows),
                "common_potential": potential,
                "provider_calls": sum(row["provider_invoked"] == "True" for row in rows),
                "uncertain_reference_rows": len(rows),
            }
        )
    write_csv(output / "comparison.csv", summaries)
    (output / "comparison_manifest.json").write_text(
        json.dumps(
            {
                "workload_sha256": freeze["workload_sha256"],
                "comparison_sha256": digest(output / "comparison.csv"),
                "runner_sha256": digest(Path(__file__)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "run", "analyze"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.action == "build":
        build(output)
    elif args.action == "run":
        asyncio.run(run(output))
    else:
        analyze(output)


if __name__ == "__main__":
    main()
