"""Chronological cache replay with explicit answer text and exact-key lookup.

Cross-pair answer relationships are not labelled by QQP/PAWS. Accepted cross-pair
candidates are counted as *unknown*, never as correct or incorrect.
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import asdict, dataclass

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.cache.answer_policy import AnswerPolicy  # noqa: E402
from app.cache.policy import CachePolicy  # noqa: E402
from app.cache.verifier import NliVerifier  # noqa: E402
from evaluation.datasets import Pair, qqp  # noqa: E402
from evaluation.reproduce import ROOT, _vector_cache  # noqa: E402

_DENSITY_WINDOW = 0.1  # matches the live in-process retrieval window


@dataclass(slots=True)
class _Entry:
    query: str
    answer: str | None
    pair_index: int
    variant: str
    vector: np.ndarray
    written_at: int
    last_used: int


@dataclass(frozen=True, slots=True)
class ReplayResult:
    requests: int
    accepted_known: int
    accepted_unknown: int
    accepted_known_false: int
    upstream_calls: int
    intended_retrieval_opportunities: int
    intended_retrieval_successes: int
    positive_density_lookups: int
    mean_density: float
    max_resident_entries: int


def replay(  # noqa: PLR0912, PLR0913, PLR0915 - chronological replay owns event state
    pairs: list[Pair],
    vectors: dict[str, np.ndarray],
    policy: CachePolicy,
    *,
    requests: int,
    seed: int,
    capacity: int,
    ttl_steps: int,
    tenants: int = 3,
    exact: bool = False,
    answer_aliases: dict[str, frozenset[str]] | None = None,
    answers_by_query: dict[str, str] | None = None,
    answer_policy: AnswerPolicy | None = None,
    answer_verifier: NliVerifier | None = None,
) -> ReplayResult:
    """Replay Zipf-popular intents, filling the cache only after each miss."""
    if not pairs or requests <= 0 or capacity <= 0 or ttl_steps <= 0 or tenants <= 0:
        raise ValueError("Replay requires nonempty pairs and positive parameters")
    if answer_aliases is not None and any(
        query not in answer_aliases
        for pair in pairs
        for query in (pair.stored_query, pair.incoming_query)
    ):
        raise ValueError("Gold replay requires an alias set for every question")
    if answer_aliases is not None and answers_by_query is None:
        raise ValueError("Answer-labelled replay requires the actual stored answer for each query")
    rng = random.Random(seed)
    weights = [1 / (rank + 1) ** 1.1 for rank in range(len(pairs))]
    order = rng.choices(range(len(pairs)), weights=weights, k=requests)
    seen: set[int] = set()
    cache: dict[int, list[_Entry]] = {tenant: [] for tenant in range(tenants)}
    accepted_known = accepted_unknown = accepted_known_false = upstream = 0
    opportunities = successes = positive_density = 0
    density_sum = 0.0
    lookups = max_resident = 0
    for step, index in enumerate(order):
        pair = pairs[index]
        tenant = index % tenants
        variant = "incoming" if index in seen else "stored"
        seen.add(index)
        query = pair.incoming_query if variant == "incoming" else pair.stored_query
        vec = vectors[query] if not exact else None
        entries = cache[tenant]
        entries[:] = [entry for entry in entries if step - entry.written_at < ttl_steps]
        candidate = None
        density = 0.0
        if entries and exact:
            candidate = next((entry for entry in entries if entry.query == query), None)
            best_sim = 1.0 if candidate is not None else -1.0
            if variant == "incoming" and any(entry.pair_index == index for entry in entries):
                opportunities += 1
                successes += candidate is not None and candidate.pair_index == index
        elif entries:
            assert vec is not None
            matrix = np.stack([entry.vector for entry in entries])
            sims = matrix @ vec
            best_index = int(np.argmax(sims))
            best_sim = float(sims[best_index])
            candidate = entries[best_index]
            within = int(np.count_nonzero((sims < best_sim) & (best_sim - sims <= _DENSITY_WINDOW)))
            density = min(1.0, within / len(sims))
            density_sum += density
            positive_density += density > 0
            lookups += 1
            if variant == "incoming" and any(entry.pair_index == index for entry in entries):
                opportunities += 1
                successes += candidate.pair_index == index
        if candidate is not None:
            hit = exact
            if answer_policy is not None and not exact:
                if answer_verifier is None:
                    raise ValueError("Answer-aware replay requires a verifier")
                hit = (
                    answer_policy.decide(
                        query, candidate.query, candidate.answer or "", best_sim, answer_verifier
                    ).action
                    == "ACCEPT"
                )
            elif not exact:
                hit, _, _ = policy.decide(query, candidate.query, best_sim, density)
            if hit:
                candidate.last_used = step
                if answer_aliases is not None:
                    from evaluation.gold_answers import normalize_answer  # noqa: PLC0415

                    actual = normalize_answer(candidate.answer or "")
                    if actual:
                        accepted_known += 1
                        accepted_known_false += actual not in answer_aliases[query]
                    else:
                        accepted_unknown += 1
                elif candidate.pair_index != index:
                    accepted_unknown += 1
                else:
                    accepted_known += 1
                    if (
                        variant == "incoming"
                        and candidate.variant == "stored"
                        and not pair.equivalent
                    ):
                        accepted_known_false += 1
                continue
        upstream += 1
        answer = answers_by_query.get(query) if answers_by_query else pair.cached_answer
        stored_vec = vectors[query]
        entries.append(_Entry(query, answer, index, variant, stored_vec, step, step))
        if len(entries) > capacity:
            oldest_index = min(
                range(len(entries)), key=lambda position: entries[position].last_used
            )
            entries.pop(oldest_index)
        max_resident = max(max_resident, sum(map(len, cache.values())))
    return ReplayResult(
        requests,
        accepted_known,
        accepted_unknown,
        accepted_known_false,
        upstream,
        opportunities,
        successes,
        positive_density,
        density_sum / lookups if lookups else 0.0,
        max_resident,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=1500)
    parser.add_argument("--pairs", type=int, default=1000)
    args = parser.parse_args()
    corpus = qqp(ROOT / "data" / "qqp.tsv")
    random.Random(42).shuffle(corpus)
    corpus = corpus[: args.pairs]
    vectors = _vector_cache(corpus)
    rows = []
    for capacity in (10, 100):
        for name, policy, exact in (
            ("exact", CachePolicy(), True),
            ("static_0.72", CachePolicy(use_adaptive=False, use_verifier=False), False),
            ("adaptive_tier1", CachePolicy(), False),
        ):
            result = replay(
                corpus,
                vectors,
                policy,
                requests=args.requests,
                seed=11,
                capacity=capacity,
                ttl_steps=500,
                exact=exact,
            )
            rows.append({"capacity_per_tenant": capacity, "system": name, **asdict(result)})
    target = ROOT / "evaluation" / "results" / "stream_proxy.csv"
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    plt.figure(figsize=(6.5, 4))
    for name in ("exact", "static_0.72", "adaptive_tier1"):
        selected = [row for row in rows if row["system"] == name]
        plt.plot(
            [row["max_resident_entries"] for row in selected],
            [row["accepted_known"] / row["requests"] for row in selected],
            marker="o",
            label=name,
        )
    plt.xlabel("Maximum resident entries across tenants")
    plt.ylabel("Known same-pair accepts / requests")
    plt.title("QQP pair-proxy replay (cross-pair truth unknown)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(ROOT / "evaluation" / "results" / "stream_proxy.png", dpi=150)
    plt.close()
    print(target)


if __name__ == "__main__":
    main()
