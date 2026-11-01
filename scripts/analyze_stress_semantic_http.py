"""Generate analysis solely from frozen HTTP request CSVs."""
# ruff: noqa: E501, PLR0912, PLR0915, PLR2004

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

POLICIES = ("exact", "static", "answer_aware")
CAPACITIES = ("sufficient", "deployment")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path: Path, data: list[dict]) -> None:
    if not data:
        path.write_text(
            "policy,capacity,id,question,reference_answer,actual_answer,"
            "selected_cached_query,selected_cached_answer,reason,explanation\n",
            encoding="utf-8",
        )
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    offset = (len(ordered) - 1) * p
    lower = int(offset)
    return round(
        ordered[lower]
        + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (offset - lower),
        3,
    )


def band(row: dict) -> str:
    value = row["distance_from_previous_family"]
    if not value:
        return "first_family_arrival"
    distance = int(value)
    if distance <= 10:
        return "short_1_10"
    if distance <= 200:
        return "medium_11_200"
    return "long_over_200"


def aggregate(data: list[dict]) -> dict:
    counts = Counter(row["outcome"] for row in data)
    opportunities = sum(row["suitable_answer_present"] == "True" for row in data)
    incorrect = counts["incorrect_acceptance"]
    correct = counts["correct_hit"]
    warm = [float(row["http_latency_ms"]) for row in data[1:] if row["http_status"] == "200"]
    gateway = [float(row["gateway_latency_ms"]) for row in data[1:] if row["http_status"] == "200"]
    stages = [json.loads(row["stage_latency_ms"]) for row in data if row["http_status"] == "200"]
    stage_lookup = [float(item["cache_lookup"]) for item in stages if "cache_lookup" in item]
    stage_provider = [float(item["provider"]) for item in stages if "provider" in item]
    stage_write = [float(item["cache_write"]) for item in stages if "cache_write" in item]
    return {
        "requests": len(data),
        "completed": sum(row["http_status"] == "200" for row in data),
        "failed": counts["runtime_failure"],
        "correct_hits": correct,
        "suspected_incorrect_hits": incorrect,
        "reuse_opportunities": opportunities,
        "reuse_per_opportunity": round(correct / opportunities, 4) if opportunities else None,
        "unnecessary_provider_calls": sum(
            row["suitable_answer_present"] == "True" and row["provider_invoked"] == "True"
            for row in data
        ),
        "provider_calls": sum(row["provider_invoked"] == "True" for row in data),
        "cold_misses": counts["cold_miss"],
        "expiry_or_eviction_misses": counts["expiry_or_eviction_miss"],
        "retrieval_misses": counts["retrieval_miss"],
        "verifier_false_rejections": counts["verifier_false_rejection"],
        "correct_rejections_of_unsuitable_selected": counts[
            "correct_rejection_unsuitable_candidate"
        ],
        "bypasses": counts["bypass"],
        "first_http_ms": float(data[0]["http_latency_ms"]) if data else None,
        "warm_http_n": len(warm),
        "warm_http_p50_ms": percentile(warm, 0.5),
        "warm_http_p95_ms": percentile(warm, 0.95),
        "warm_http_p99_ms": percentile(warm, 0.99),
        "warm_gateway_p50_ms": percentile(gateway, 0.5),
        "warm_gateway_p95_ms": percentile(gateway, 0.95),
        "warm_gateway_p99_ms": percentile(gateway, 0.99),
        "actual_verifier_invocations": sum(row["verifier_invoked"] == "True" for row in data),
        "lookup_stage_p50_ms": percentile(stage_lookup, 0.5),
        "provider_stage_p50_ms": percentile(stage_provider, 0.5),
        "cache_write_stage_p50_ms": percentile(stage_write, 0.5),
        "lookup_stage_n": len(stage_lookup),
        "provider_stage_n": len(stage_provider),
        "cache_write_stage_n": len(stage_write),
    }


def family_interval(
    data: list[dict], numerator: str, denominator: str
) -> tuple[float, float] | None:
    groups = defaultdict(list)
    for row in data:
        groups[row["family_id"]].append(row)
    families = list(groups.values())
    rng = random.Random(90210)
    rates = []
    for _ in range(1000):
        sample = [rng.choice(families) for _ in families]
        selected = [row for group in sample for row in group]
        top = sum(row["outcome"] == numerator for row in selected)
        bottom = (
            sum(row["suitable_answer_present"] == "True" for row in selected)
            if denominator == "live"
            else len(selected)
        )
        if bottom:
            rates.append(top / bottom)
    if not rates:
        return None
    lower, upper = percentile(rates, 0.025), percentile(rates, 0.975)
    assert lower is not None and upper is not None
    return lower, upper


def explain(row: dict) -> str:
    outcome = row["outcome"]
    if outcome == "incorrect_acceptance":
        return "Cached answer differs from the authored reference for this question. Review source alias/completeness."
    if outcome == "verifier_false_rejection":
        return "Selected cached answer matched the authored reference, but the policy declined it."
    if outcome == "retrieval_miss":
        return (
            "A matching controlled answer was live in Redis, but retrieval selected no candidate."
        )
    return "A matching controlled answer was live in Redis, but a different candidate was selected and declined."


def analyze(output: Path) -> None:
    freeze = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    if sha(output / "workload.csv") != freeze["workload_sha256"]:
        raise ValueError("Workload hash changed")
    seen_answers = set()
    common_opportunities = 0
    for workload_row in rows(output / "workload.csv"):
        common_opportunities += workload_row["reference_answer"] in seen_answers
        seen_answers.add(workload_row["reference_answer"])
    reuse_gaps = sorted(
        int(row["distance_from_previous_family"])
        for row in rows(output / "workload.csv")
        if row["distance_from_previous_family"]
    )
    all_summary = []
    categories: list[dict] = []
    distances: list[dict] = []
    wrong = []
    unnecessary = []
    manifests = {}
    for capacity in CAPACITIES:
        for policy in POLICIES:
            folder = output / f"{policy}_{capacity}"
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            if sha(folder / "requests.csv") != manifest["requests_sha256"]:
                raise ValueError(f"Request hash changed: {folder}")
            data = rows(folder / "requests.csv")
            if len(data) != freeze["requests"]:
                raise ValueError(f"Incomplete run: {folder}")
            if data[0]["cache"] != "MISS" or data[0]["suitable_answer_present"] != "False":
                raise ValueError(f"Run did not begin with an empty evaluation cache: {folder}")
            summary = {"policy": policy, "capacity": capacity, **aggregate(data)}
            summary["common_potential_reuse_opportunities"] = common_opportunities
            summary["hits_over_common_potential"] = round(
                summary["correct_hits"] / common_opportunities, 4
            )
            summary["reuse_live_family_bootstrap_95"] = family_interval(data, "correct_hit", "live")
            summary["suspected_wrong_per_request_family_bootstrap_95"] = family_interval(
                data, "incorrect_acceptance", "requests"
            )
            summary["startup_ms"] = json.loads((folder / "summary.json").read_text())["startup_ms"]
            all_summary.append(summary)
            manifests[f"{policy}_{capacity}"] = manifest["requests_sha256"]
            for field, destination in (("kind", categories), ("distance", distances)):
                groups = defaultdict(list)
                for row in data:
                    groups[row["kind"] if field == "kind" else band(row)].append(row)
                for group, subset in sorted(groups.items()):
                    destination.append(
                        {"policy": policy, "capacity": capacity, field: group, **aggregate(subset)}
                    )
            for row in data:
                item = {"policy": policy, "capacity": capacity, **row, "explanation": explain(row)}
                if row["outcome"] == "incorrect_acceptance":
                    wrong.append(item)
                if row["suitable_answer_present"] == "True" and row["provider_invoked"] == "True":
                    unnecessary.append(item)
    write(output / "aggregate.csv", all_summary)
    write(output / "by_category.csv", categories)
    write(output / "by_distance.csv", distances)
    write(output / "all_suspected_incorrect_accepts.csv", wrong)
    write(output / "unnecessary_misses.csv", unnecessary)
    selected = []
    for capacity in CAPACITIES:
        for policy in POLICIES:
            subset = [
                item
                for item in unnecessary
                if item["capacity"] == capacity and item["policy"] == policy
            ]
            selected.extend(subset[:10])
    write(output / "failure_examples.csv", [*wrong, *selected])
    lines = [
        "# Frozen 1,000-request controlled-answer HTTP stress evaluation",
        "",
        "Source: [NQ-Open train](https://github.com/google-research-datasets/natural-questions/tree/master/nq_open), CC BY-SA 3.0. The questions and answers are derived from NQ-Open; three paraphrases and one entity-swap hard negative per family are authored transformations.",
        "",
        "**Label limit:** These are authored controls against NQ short answers, not independently human-reviewed answer validity. NQ references can omit co-writers. A mismatch is a suspected incorrect acceptance requiring source review. This workload is not representative production traffic.",
        "",
        f"Workload SHA-256: `{freeze['workload_sha256']}`. Policy SHA-256: `{freeze['policy_sha256']}`. Seed: {freeze['seed']}. No thresholds were retuned after the run.",
        "Static means fixed MiniLM cosine threshold 0.72 without the structural verifier; answer-aware means the frozen answer-policy artifact with NLI. Both use the same RediSearch retrieval path. Exact mode remains the gateway default outside this evaluation.",
        f"Same-family request gaps: min {reuse_gaps[0]}, median {reuse_gaps[len(reuse_gaps) // 2]}, max {reuse_gaps[-1]}; all 1,000 row positions and previous-family distances are in `workload.csv`.",
        "",
        "| Capacity | Policy | Completed | Reference-matching hits | Suspected wrong hits | Live opportunities | Hits/live | Hits/common potential | Unnecessary provider calls | Provider calls | Warm HTTP p50 / p95 / p99 ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in all_summary:
        lines.append(
            f"| {item['capacity']} | {item['policy']} | {item['completed']}/{item['requests']} | {item['correct_hits']} | {item['suspected_incorrect_hits']} | {item['reuse_opportunities']} | {item['reuse_per_opportunity']} | {item['hits_over_common_potential']} | {item['unnecessary_provider_calls']} | {item['provider_calls']} | {item['warm_http_p50_ms']} / {item['warm_http_p95_ms']} / {item['warm_http_p99_ms']} (n={item['warm_http_n']}) |"
        )
    static = next(
        item
        for item in all_summary
        if item["policy"] == "static" and item["capacity"] == "sufficient"
    )
    aware = next(
        item
        for item in all_summary
        if item["policy"] == "answer_aware" and item["capacity"] == "sufficient"
    )
    exact_full = next(
        item
        for item in all_summary
        if item["policy"] == "exact" and item["capacity"] == "sufficient"
    )
    exact_deploy = next(
        item
        for item in all_summary
        if item["policy"] == "exact" and item["capacity"] == "deployment"
    )
    lines.extend(
        [
            "",
            "## What the rows show",
            "",
            f"The answer-aware policy reduced suspected wrong hits from {static['suspected_incorrect_hits']} to {aware['suspected_incorrect_hits']} compared with the static threshold, while serving {aware['correct_hits']} reference-matching hits. It made {aware['provider_calls']} controlled-provider calls versus {static['provider_calls']} for static. The {aware['verifier_false_rejections']} answer-aware verifier false rejections are lost reuse against the authored references. These observations do not establish real-answer correctness.",
            f"Exact caching had zero hits because every text is unique. Its live reuse opportunities fell from {exact_full['reuse_opportunities']} to {exact_deploy['reuse_opportunities']} under the 256-entry deployment cap. Static and answer-aware outcomes were unchanged between capacity settings on this particular sequence.",
            "",
            "### By question form (sufficient capacity)",
            "",
            "| Policy | Form | Reference-matching hits | Suspected wrong hits | Verifier false rejections |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for item in categories:
        if item["capacity"] in {"sufficient"} and item["policy"] in {"static", "answer_aware"}:
            lines.append(
                f"| {item['policy']} | {item['kind']} | {item['correct_hits']} | {item['suspected_incorrect_hits']} | {item['verifier_false_rejections']} |"
            )
    lines.extend(
        [
            "",
            "All three authored paraphrase forms produced both reference-matching reuse and suspected wrong reuse. The fronted 'For the song ...' form had the most answer-aware false rejections. Every suspected wrong acceptance is in `all_suspected_incorrect_accepts.csv`; `failure_examples.csv` also includes concrete unnecessary misses with selected candidates, answers and reasons.",
        ]
    )
    lines.extend(
        [
            "",
            "Examples of suspected wrong acceptance from the sufficient-capacity answer-aware run:",
            "",
        ]
    )
    for item in [
        row for row in wrong if row["policy"] == "answer_aware" and row["capacity"] == "sufficient"
    ][:3]:
        lines.append(
            f"- Incoming: “{item['question']}” Cached question: “{item['selected_cached_query']}” Served: “{item['actual_answer']}”; NQ reference: “{item['reference_answer']}”."
        )
    lines.extend(
        [
            "",
            "Startup and first-request times (ms):",
            "",
            "| Capacity | Policy | Startup | First HTTP | NLI invocations |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for item in all_summary:
        lines.append(
            f"| {item['capacity']} | {item['policy']} | {item['startup_ms']} | {item['first_http_ms']} | {item['actual_verifier_invocations']} |"
        )
    lines.extend(
        [
            "",
            f"The common potential-reuse denominator is {common_opportunities} requests: an earlier question in the frozen order had the same controlled reference answer. Live-cache opportunities vary by policy and capacity; both denominators are shown.",
            "",
            "The latency rows report a single sequential local runner, not concurrent throughput. Cold startup is separate from the first HTTP request. Per-request gateway lookup, admission, provider, and cache-write stages are in `requests.csv` as `stage_latency_ms`.",
            "Family-bootstrap 95% descriptive intervals for controlled-label reuse and suspected wrong-hit rates are in `aggregate.csv`. They measure sampling variability across these 200 authored families, not uncertainty from incomplete NQ answers or production traffic.",
            "",
            "Inspect `by_category.csv`, `by_distance.csv`, `all_suspected_incorrect_accepts.csv`, and `failure_examples.csv`. Distance is the gap from the previous same-family request; it is not necessarily the distance from the nearest suitable cached answer.",
            "",
            "A miss is unnecessary only when a suitable controlled answer existed in live Redis immediately before the request. An exact-cache miss on a new text can therefore count as a lost reuse opportunity. Hard negatives can legitimately reuse a different family’s cached answer.",
            "All 1,000 question texts are unique, so exact matching has no literal repeat to hit. Its zero-hit result measures the lack of semantic reuse on this workload, not exact-cache performance on repeated identical prompts.",
            "",
        ]
    )
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    (output / "analysis_manifest.json").write_text(
        json.dumps(
            {
                "input_request_hashes": manifests,
                "aggregate_sha256": sha(output / "aggregate.csv"),
                "report_sha256": sha(output / "REPORT.md"),
                "analysis_seed": 90210,
                "code_sha256": {
                    name: sha(Path(__file__).resolve().parents[1] / name)
                    for name in (
                        "app/main.py",
                        "app/cache/semantic_cache.py",
                        "app/cache/answer_policy.py",
                        "app/providers/evaluation.py",
                        "scripts/stress_semantic_http.py",
                        "scripts/analyze_stress_semantic_http.py",
                    )
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    analyze(parser.parse_args().output.resolve())
