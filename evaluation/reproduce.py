"""Reproduce pair-level proxy measurements; never interprets paraphrase labels as answer truth."""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from functools import lru_cache
from pathlib import Path

import numpy as np

os.environ.setdefault("EMBEDDING_BACKEND", "minilm")

from app.cache.policy import CachePolicy  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.embeddings import active_backend, cosine, embed  # noqa: E402
from evaluation.datasets import Pair, fingerprint, group_split, paws, qqp, smoke, stsb  # noqa: E402
from evaluation.protocol import Decision, bootstrap_ci, metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (11, 23, 37, 53, 71)
THRESHOLDS = tuple(round(0.4 + 0.02 * i, 2) for i in range(31))
MIN_PUBLIC_ROWS = 100
FIELDS = (
    "dataset",
    "seed",
    "system",
    "split",
    "source_sha256",
    "n",
    "accepted",
    "true_accepts",
    "false_accepts",
    "coverage",
    "false_hit_among_served",
    "precision",
    "recall",
    "false_accept_among_negative",
    "auroc",
    "risk_ci_low",
    "risk_ci_high",
    "coverage_ci_low",
    "coverage_ci_high",
    "chosen_threshold",
    "label_type",
)


@lru_cache(maxsize=1)
def _batch_model():
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415 - evaluation only

    settings = get_settings()
    return SentenceTransformer(
        settings.embedding_model, revision=settings.embedding_revision or None
    )


def _vector_cache(pairs: list[Pair]) -> dict[str, np.ndarray]:
    queries = list(
        dict.fromkeys(query for pair in pairs for query in (pair.stored_query, pair.incoming_query))
    )
    if active_backend() == "hash":
        return {query: embed(query) for query in queries}
    matrix = np.asarray(
        _batch_model().encode(
            queries, batch_size=64, normalize_embeddings=True, show_progress_bar=False
        ),
        dtype=np.float32,
    )
    return dict(zip(queries, matrix, strict=True))


def _decisions(
    pairs: list[Pair], vectors: dict[str, np.ndarray], policy: CachePolicy
) -> list[Decision]:
    rows = []
    for pair in pairs:
        sim = cosine(vectors[pair.stored_query], vectors[pair.incoming_query])
        if not policy.use_adaptive and not policy.use_verifier and policy.static_threshold == 1.0:
            hit = pair.incoming_query == pair.stored_query
        else:
            hit, _, _ = policy.decide(pair.incoming_query, pair.stored_query, sim, density=0.0)
        rows.append(Decision(pair.equivalent, sim, hit, pair.source_id))
    return rows


def _tune(val: list[Pair], vectors: dict[str, np.ndarray]) -> float:
    """Select only on validation F1; deterministic stricter tie break."""
    winner, best = THRESHOLDS[-1], -1.0
    for threshold in THRESHOLDS:
        rows = _decisions(
            val,
            vectors,
            CachePolicy(use_adaptive=False, use_verifier=False, static_threshold=threshold),
        )
        tp = sum(row.accepted and row.label for row in rows)
        fp = sum(row.accepted and not row.label for row in rows)
        positives = sum(pair.equivalent for pair in val)
        f1 = 2 * tp / (positives + tp + fp) if positives + tp + fp else 0.0
        if f1 > best or (f1 == best and threshold > winner):
            winner, best = threshold, f1
    return winner


def _row(  # noqa: PLR0913, PLR0917 - an output row records all experiment identifiers
    dataset: str,
    seed: int,
    name: str,
    split_name: str,
    pairs: list[Pair],
    vectors: dict[str, np.ndarray],
    policy: CachePolicy,
    source_hash: str,
    threshold: float | None,
) -> dict[str, str | int | float | None]:
    decisions = _decisions(pairs, vectors, policy)
    result = metrics(decisions)
    risk_low, risk_high = bootstrap_ci(decisions, "false_hit_among_served", seed=seed)
    coverage_low, coverage_high = bootstrap_ci(decisions, "coverage", seed=seed)
    return {
        "dataset": dataset,
        "seed": seed,
        "system": name,
        "split": split_name,
        "source_sha256": source_hash,
        **result,
        "risk_ci_low": risk_low,
        "risk_ci_high": risk_high,
        "coverage_ci_low": coverage_low,
        "coverage_ci_high": coverage_high,
        "chosen_threshold": threshold,
        "label_type": "query_pair_proxy",
    }


def run(*, fast: bool = False) -> list[dict[str, str | int | float | None]]:
    sources = {"smoke_development_only": smoke()}
    if not fast:
        paths = {
            "qqp": (ROOT / "data" / "qqp.tsv", qqp),
            "paws": (ROOT / "data" / "paws.tsv", paws),
            "stsb": (ROOT / "data" / "stsb.tsv", stsb),
        }
        missing = [str(path) for path, _ in paths.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "Full reproduction needs source files under gitignored data/: " + ", ".join(missing)
            )
        for name, (path, loader) in paths.items():
            corpus = loader(path)
            if len(corpus) < MIN_PUBLIC_ROWS:
                raise ValueError(f"{name}: fewer than 100 valid source-labelled rows")
            random.Random(42).shuffle(corpus)
            sources[name] = corpus[: min(2000, len(corpus))]
    output: list[dict[str, str | int | float | None]] = []
    for name, corpus in sources.items():
        vectors = _vector_cache(corpus)
        source_hash = fingerprint(corpus)
        for seed in SEEDS:
            splits = group_split(corpus, seed)
            val, test = splits["val"], splits["test"]
            if not val or not test:
                raise ValueError(f"{name}: group split yielded empty val/test")
            threshold = _tune(val, vectors)
            policies = {
                "exact": CachePolicy(use_adaptive=False, use_verifier=False, static_threshold=1.0),
                "static_val_f1": CachePolicy(
                    use_adaptive=False, use_verifier=False, static_threshold=threshold
                ),
                "adaptive_tier1": CachePolicy(use_adaptive=True, use_verifier=True),
            }
            for system, policy in policies.items():
                output.append(
                    _row(
                        name,
                        seed,
                        system,
                        "test",
                        test,
                        vectors,
                        policy,
                        source_hash,
                        threshold if system == "static_val_f1" else None,
                    )
                )
    results = ROOT / "evaluation" / "results"
    results.mkdir(exist_ok=True)
    with (results / "v2_pair_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output)
    (results / "v2_manifest.json").write_text(
        json.dumps(
            {
                "seeds": SEEDS,
                "datasets": {k: fingerprint(v) for k, v in sources.items()},
                "label_type": "query_pair_proxy",
                "mode": "fast" if fast else "full",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="smoke fixture only")
    args = parser.parse_args()
    for row in run(fast=args.fast):
        print(
            f"{row['dataset']} seed={row['seed']} {row['system']}: "
            f"coverage={row['coverage']:.3f}, risk={row['false_hit_among_served']}"
        )
    print("Pair-label proxy only. No answer-reuse claim.")


if __name__ == "__main__":
    main()
