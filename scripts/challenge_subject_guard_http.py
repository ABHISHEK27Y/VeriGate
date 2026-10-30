"""Freeze authored identity challenges, then compare both policies over live HTTP.

The catalog is fictional and defines controlled answers, not real-world facts.
Build must complete before run; a built directory is immutable.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
from collections import Counter
from pathlib import Path

from scripts.stress_semantic_http import POLICY, ROOT, digest, run_one, write_csv

WORKS = (
    ("song", "The Northbound Letter", "Northbound Letters", "Mira Vale", "Elias Reed"),
    ("song", "Glass Harbor", "The Glass Harbors", "Nora Flint", "Ilan Moss"),
    ("book", "The Silver Orchard", "Silver Orchards", "Tessa Rowe", "Damon Pike"),
    ("book", "A Lantern in Winter", "Lanterns in Winter", "Rhea Stone", "Caleb Voss"),
    ("film", "The Last Crossing", "The Last Crossings", "Uma Grey", "Felix Shore"),
    ("film", "Quiet Horizon", "The Quiet Horizons", "Lena Hart", "Otto Finch"),
    ("poem", "The Blue Window", "Blue Windows", "Ada Fenn", "Jules North"),
    ("poem", "Beyond the River", "Beyond the Rivers", "Cora Hale", "Niko Ash"),
)
OTHER = (
    (
        "person",
        "Who founded the town of Eastmere?",
        "Who established Eastmere?",
        "Who founded the town of Westmere?",
        "Sana Bell",
        "Pavel Rios",
    ),
    (
        "place",
        "Where was the explorer Tavi Ren born?",
        "What is Tavi Ren's birthplace?",
        "Where was the explorer Tavi Ryn born?",
        "Dunvale",
        "Marshport",
    ),
    (
        "date",
        "When did the Cedar Bridge open?",
        "What was the opening year of Cedar Bridge?",
        "When did the Cedar Tunnel open?",
        "1984",
        "1987",
    ),
)


def build(output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    rows: list[dict] = []
    answers: dict[str, str] = {}
    catalog: list[dict] = []
    for index, (domain, title, decoy, answer, decoy_answer) in enumerate(WORKS):
        verb = "directed" if domain == "film" else "wrote"
        role = "director" if domain == "film" else "writer"
        alternate_type = {"book": "novel", "film": "movie"}.get(domain, domain)
        # The article/case/punctuation form is a declared alias of the same
        # fictional work; the similar plural title is a different work.
        variation = title.removeprefix("The ").removeprefix("A ")
        variants = (
            ("seed", f"Who {verb} the {domain} {title}?", answer, "seed"),
            (
                "title_variation",
                f"Name the {role} of the {alternate_type} {variation.lower()}.",
                answer,
                "valid",
            ),
            ("paraphrase", f"For the {domain} {title}, who {verb} it?", answer, "valid"),
            ("different_work", f"Who {verb} the {domain} {decoy}?", decoy_answer, "invalid"),
        )
        catalog.append(
            {
                "domain": domain,
                "seed_title": title,
                "declared_alias": variation,
                "different_title": decoy,
                "seed_answer": answer,
                "different_answer": decoy_answer,
                "evidence": "fictional authored catalog",
            }
        )
        for kind, question, reference, relation in variants:
            answers[question] = reference
            rows.append(
                {
                    "id": f"work-{index:02d}:{kind}",
                    "family_id": f"work-{index:02d}",
                    "kind": kind,
                    "domain": domain,
                    "question": question,
                    "reference_answer": reference,
                    "family_cached_answer": answer,
                    "family_answer_reusable": relation != "invalid",
                    "relation": relation,
                    "source_url": "local authored catalog",
                    "evidence": ("catalog.json; distinct works have distinct stipulated answers"),
                    "label_status": "authored_control",
                    "uncertainty": (
                        "Fictional identities and answers; tests decisions, not factual accuracy"
                    ),
                    "position": len(rows) + 1,
                }
            )
    for index, (domain, seed, paraphrase, near, answer, near_answer) in enumerate(OTHER):
        catalog.append(
            {
                "domain": domain,
                "seed_question": seed,
                "paraphrase": paraphrase,
                "different_question": near,
                "seed_answer": answer,
                "different_answer": near_answer,
                "evidence": "fictional authored catalog; outside named-work syntax",
            }
        )
        for kind, question, reference, relation in (
            ("seed", seed, answer, "seed"),
            ("paraphrase", paraphrase, answer, "valid"),
            ("near_match", near, near_answer, "invalid"),
        ):
            answers[question] = reference
            rows.append(
                {
                    "id": f"other-{index:02d}:{kind}",
                    "family_id": f"other-{index:02d}",
                    "kind": kind,
                    "domain": domain,
                    "question": question,
                    "reference_answer": reference,
                    "family_cached_answer": answer,
                    "family_answer_reusable": relation != "invalid",
                    "relation": relation,
                    "source_url": "local authored catalog",
                    "evidence": (
                        "catalog.json; different entities have distinct stipulated answers"
                    ),
                    "label_status": "authored_control",
                    "uncertainty": (
                        "Fictional identities and answers; tests decisions, not factual accuracy"
                    ),
                    "position": len(rows) + 1,
                }
            )
    prior = (
        ROOT / "evaluation/runs/nq_song_stress_20261030_v3/workload.csv",
        ROOT / "evaluation/runs/subject_guard_holdout_20261030_v1/workload.csv",
        ROOT / "evaluation/runs/subject_guard_holdout_20261030_v2/workload.csv",
    )
    old_text = "\n".join(path.read_text(encoding="utf-8").casefold() for path in prior)
    if any(title.casefold() in old_text for _, title, _, _, _ in WORKS):
        raise ValueError("Challenge subject overlaps an earlier workload")
    if len(answers) != len(rows):
        raise ValueError("Duplicate challenge question")
    output.mkdir(parents=True)
    write_csv(output / "workload.csv", rows)
    (output / "provider_answers.json").write_text(json.dumps(answers, indent=2), encoding="utf-8")
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    freeze = {
        "requests": len(rows),
        "workload_sha256": digest(output / "workload.csv"),
        "provider_answers_sha256": digest(output / "provider_answers.json"),
        "catalog_sha256": digest(output / "catalog.json"),
        "policy_sha256": digest(POLICY),
        "policy_artifact": POLICY.relative_to(ROOT).as_posix(),
        "comparison": {"unchanged": False, "guarded": True},
        "settings": {
            mode: {"cache_ttl_sec": 86400, "max_cache_entries_per_tenant": 256}
            for mode in ("unchanged", "guarded")
        },
        "source": "fictional authored controlled catalog",
        "selection": (
            "8 named-work families (song, book, film, poem), 3 out-of-scope families "
            "(person, place, date); seed, valid variation, and identity near match"
        ),
        "label_limit": (
            "Author-stipulated fictional answers; no independent human or real-world labels"
        ),
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "nli_model": "cross-encoder/nli-deberta-v3-xsmall",
        "nli_revision": "a150876415327c80daeff35ca6f68f5ed8cf5c24",
    }
    (output / "freeze.json").write_text(json.dumps(freeze, indent=2), encoding="utf-8")


async def run(output: Path) -> None:
    freeze = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    for path, key in (
        (output / "workload.csv", "workload_sha256"),
        (output / "provider_answers.json", "provider_answers_sha256"),
        (output / "catalog.json", "catalog_sha256"),
        (POLICY, "policy_sha256"),
    ):
        if digest(path) != freeze[key]:
            raise ValueError(f"Frozen input changed: {path}")
    with (output / "workload.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    answers = json.loads((output / "provider_answers.json").read_text(encoding="utf-8"))
    original = os.environ.get("ANSWER_POLICY_SUBJECT_GUARD")
    try:
        for mode, guard in freeze["comparison"].items():
            if (output / f"answer_aware_{mode}").exists():
                raise FileExistsError(mode)
            os.environ["ANSWER_POLICY_SUBJECT_GUARD"] = str(guard).lower()
            summary = await run_one(output, "answer_aware", mode, rows, answers, freeze)
            manifest_path = output / f"answer_aware_{mode}" / "manifest.json"
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
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if digest(directory / "requests.csv") != manifest["requests_sha256"]:
            raise ValueError("Run observations changed")
        with (directory / "requests.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != freeze["requests"]:
            raise ValueError("Incomplete run")
        times = [float(row["http_latency_ms"]) for row in rows if row["http_status"] == "200"]
        gateway = [float(row["gateway_latency_ms"]) for row in rows if row["http_status"] == "200"]
        valid = [row for row in rows if row["relation"] == "valid"]
        invalid = [row for row in rows if row["relation"] == "invalid"]
        summaries.append(
            {
                "mode": mode,
                "requests": len(rows),
                "completed": sum(row["http_status"] == "200" for row in rows),
                "valid_reuse": sum(row["outcome"] == "correct_hit" for row in valid),
                "valid_denominator": len(valid),
                "unnecessary_rejections": sum(
                    row["outcome"] == "verifier_false_rejection" for row in valid
                ),
                "invalid_accepts": sum(row["outcome"] == "incorrect_acceptance" for row in invalid),
                "invalid_denominator": len(invalid),
                "provider_calls": sum(row["provider_invoked"] == "True" for row in rows),
                "median_http_ms": round(statistics.median(times), 3),
                "p95_http_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 3),
                "median_gateway_ms": round(statistics.median(gateway), 3),
                "reasons": dict(Counter(row["reason"] for row in rows)),
            }
        )
    (output / "comparison.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")


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
