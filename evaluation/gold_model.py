"""Five-seed NQ-Open gold-answer-match study with pinned local NLI features.

The oracle cached answer is an NQ reference string. This tests a factoid proxy,
not whether a generated LLM answer would be correct or complete.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, cast

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.cache.accept_model import FEATURE_NAMES, features
from app.cache.policy import CachePolicy
from app.cache.risk import binomial_upper, select_threshold
from app.config import get_settings
from app.embeddings import active_backend, cosine, tokenize
from evaluation.datasets import Pair, group_split, paws
from evaluation.gold_answers import load_pairs, normalize_answer
from evaluation.protocol import Decision, bootstrap_ci, metrics
from evaluation.reproduce import ROOT, SEEDS, THRESHOLDS, _vector_cache

RESULTS = ROOT / "evaluation" / "results"
GOLD = ROOT / "data" / "gold_answer_pairs.tsv"
TARGETS = (0.01, 0.02, 0.05)
RISK_GRID = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999)
GOLD_SPLIT_FRACTIONS = (0.5, 0.1, 0.25, 0.15)
_ANTONYMS = (
    ("before", "after"),
    ("increase", "decrease"),
    ("higher", "lower"),
    ("more", "less"),
    ("true", "false"),
    ("yes", "no"),
    ("allow", "deny"),
    ("include", "exclude"),
)
NLI_FEATURE_NAMES = (*FEATURE_NAMES, "antonym_mismatch", "nli_forward", "nli_reverse")
MODEL_NAMES = ("learned_with_nli", "learned_without_nli")
ERROR_POLICIES = ("static_val_f1", "adaptive_tier1", "learned_with_nli")
ERROR_SAMPLE_SIZE = 100


def _antonym_mismatch(first: str, second: str) -> float:
    first_tokens, second_tokens = set(tokenize(first)), set(tokenize(second))
    return float(
        any(
            (left in first_tokens and right in second_tokens)
            or (right in first_tokens and left in second_tokens)
            for left, right in _ANTONYMS
        )
    )


def _nli_features(pairs: list[Pair], corpus_name: str) -> np.ndarray:
    from sentence_transformers import CrossEncoder  # noqa: PLC0415 - research-only dependency

    settings = get_settings()
    digest = hashlib.sha256(
        (
            corpus_name
            + settings.nli_revision
            + "\n"
            + "\n".join(f"{p.stored_query}\t{p.incoming_query}" for p in pairs)
        ).encode()
    ).hexdigest()
    cache = ROOT / "data" / f"nli_{corpus_name}_{digest[:16]}.npz"
    if cache.is_file():
        with np.load(cache) as saved:
            if str(saved["digest"]) == digest and saved["scores"].shape == (len(pairs), 2):
                return np.asarray(saved["scores"], dtype=np.float64)
    model = CrossEncoder(settings.nli_model, revision=settings.nli_revision or None)
    labels = model.model.config.id2label
    entail = next(
        (int(index) for index, label in labels.items() if "entail" in label.casefold()),
        None,
    )
    if entail is None:
        raise ValueError("Pinned NLI model has no entailment class")
    requests = [(p.stored_query, p.incoming_query) for p in pairs] + [
        (p.incoming_query, p.stored_query) for p in pairs
    ]
    predictions = np.asarray(
        model.predict(requests, batch_size=32, apply_softmax=True, show_progress_bar=False)
    )
    if predictions.shape != (2 * len(pairs), len(labels)):
        raise ValueError("Unexpected NLI prediction shape")
    scores = np.column_stack((predictions[: len(pairs), entail], predictions[len(pairs) :, entail]))
    if not np.isfinite(scores).all():
        raise ValueError("NLI produced nonfinite scores")
    np.savez_compressed(cache, digest=digest, scores=scores)
    return np.asarray(scores, dtype=np.float64)


def _matrix(pairs: list[Pair], name: str) -> np.ndarray:
    vectors = _vector_cache(pairs)
    nli = _nli_features(pairs, name)
    return np.asarray(
        [
            (
                *features(
                    pair.incoming_query,
                    pair.stored_query,
                    cosine(vectors[pair.incoming_query], vectors[pair.stored_query]),
                    0.0,
                    pair.cached_answer or "",
                ),
                _antonym_mismatch(pair.incoming_query, pair.stored_query),
                *nli[index],
            )
            for index, pair in enumerate(pairs)
        ],
        dtype=np.float64,
    )


def _labels(pairs: list[Pair], *, gold: bool) -> np.ndarray:
    if gold and any(pair.answer_reusable is None for pair in pairs):
        raise ValueError("Gold experiment requires answer-match labels on every row")
    return np.asarray(
        [int(bool(pair.answer_reusable) if gold else pair.equivalent) for pair in pairs],
        dtype=np.int8,
    )


def _choose_f1(scores: np.ndarray, labels: np.ndarray, candidates: tuple[float, ...]) -> float:
    best_threshold, best_f1 = candidates[-1], -1.0
    positives = int(labels.sum())
    for threshold in candidates:
        accepted = scores >= threshold
        true = int((accepted & (labels == 1)).sum())
        total = int(accepted.sum())
        f1 = 2 * true / (positives + total) if positives + total else 0.0
        if f1 > best_f1 or (f1 == best_f1 and threshold > best_threshold):
            best_threshold, best_f1 = threshold, f1
    return float(best_threshold)


def _question_component_ids(pairs: list[Pair]) -> list[str]:
    """Keep repeated questions together when bootstrapping held-out rows."""
    parent = list(range(len(pairs)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seen: dict[str, int] = {}
    for index, pair in enumerate(pairs):
        for query in (pair.stored_query, pair.incoming_query):
            key = " ".join(query.casefold().split())
            if key in seen:
                parent[root(index)] = root(seen[key])
            else:
                seen[key] = index
    return [f"{pair.source}:{root(index)}" for index, pair in enumerate(pairs)]


def _record(  # noqa: PLR0913 - experiment records need identifiers and decisions
    pairs: list[Pair], scores: np.ndarray, threshold: float, *, seed: int, system: str, source: str
) -> dict[str, Any]:
    gold = source == "nq_open"
    groups = _question_component_ids(pairs)
    decisions = [
        Decision(bool(label), float(score), bool(score >= threshold), group)
        for pair, score, label, group in zip(
            pairs, scores, _labels(pairs, gold=gold), groups, strict=True
        )
    ]
    risk_low, risk_high = bootstrap_ci(decisions, "false_hit_among_served", seed=seed)
    coverage_low, coverage_high = bootstrap_ci(decisions, "coverage", seed=seed)
    return {
        "train_source": "nq_open",
        "test_source": source,
        "seed": seed,
        "system": system,
        "chosen_threshold": threshold,
        **metrics(decisions),
        "risk_ci_low": risk_low,
        "risk_ci_high": risk_high,
        "coverage_ci_low": coverage_low,
        "coverage_ci_high": coverage_high,
        "label_type": "gold_answer_match" if gold else "query_pair_proxy",
    }


def _part(matrix: np.ndarray, positions: dict[int, int], pairs: list[Pair]) -> np.ndarray:
    return matrix[[positions[id(pair)] for pair in pairs]]


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _predict(  # noqa: PLR0913 - trained components stay separate for the ablation
    matrix: np.ndarray,
    columns: slice,
    scaler: StandardScaler,
    model: LogisticRegression,
    calibrator: IsotonicRegression,
) -> np.ndarray:
    raw = model.predict_proba(scaler.transform(matrix[:, columns]))[:, 1]
    return np.asarray(calibrator.predict(raw), dtype=np.float64)


def _gold_metadata() -> dict[str, dict[str, Any]]:
    with GOLD.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if len(rows) != len({row["source_id"] for row in rows}):
        raise ValueError("Gold source IDs must be unique for error analysis")
    return {row["source_id"]: row for row in rows}


def _granularity_difference(first: list[str], second: list[str]) -> bool:
    """Flag strict token containment in any answer alias; this is only a heuristic."""
    for left in first:
        left_tokens = normalize_answer(left).split()
        for right in second:
            right_tokens = normalize_answer(right).split()
            short, long = sorted((left_tokens, right_tokens), key=len)
            if (
                short
                and len(short) < len(long)
                and any(
                    long[index : index + len(short)] == short
                    for index in range(len(long) - len(short) + 1)
                )
            ):
                return True
    return False


def _false_accepts(  # noqa: PLR0913 - decisions and provenance must remain aligned
    pairs: list[Pair],
    scores: np.ndarray,
    threshold: float,
    *,
    seed: int,
    policy: str,
    metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for pair, score in zip(pairs, scores, strict=True):
        if pair.answer_reusable is not False or score < threshold:
            continue
        source = metadata[pair.source_id]
        stored = json.loads(source["stored_aliases"])
        incoming = json.loads(source["incoming_aliases"])
        output.append(
            {
                "policy": policy,
                "seed": seed,
                "source_id": pair.source_id,
                "stored_query": pair.stored_query,
                "incoming_query": pair.incoming_query,
                "stored_gold_answers": source["stored_aliases"],
                "incoming_gold_answers": source["incoming_aliases"],
                "negative_category": source["negative_type"],
                "policy_score": float(score),
                "policy_threshold": threshold,
                "granularity_difference_heuristic": int(_granularity_difference(stored, incoming)),
                "label_type": "gold_answer_match",
            }
        )
    return output


def _sample_false_accepts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sampled = []
    for index, policy in enumerate(ERROR_POLICIES):
        candidates = [row for row in rows if row["policy"] == policy]
        random.Random(10_000 + index).shuffle(candidates)
        seen = set()
        for row in candidates:
            if row["source_id"] in seen:
                continue
            sampled.append(row)
            seen.add(row["source_id"])
            if len(seen) == ERROR_SAMPLE_SIZE:
                break
        if len(seen) != ERROR_SAMPLE_SIZE:
            raise ValueError(f"Insufficient distinct false accepts for {policy}: {len(seen)}")
    return sampled


def run(*, include_risk: bool = False) -> None:  # noqa: PLR0912, PLR0915 - aligned split state
    if active_backend() != "minilm":
        raise ValueError("Gold model experiment requires pinned MiniLM embeddings")
    gold, _ = load_pairs(GOLD)
    gold_metadata = _gold_metadata()
    paws_rows = paws(ROOT / "data" / "paws.tsv")
    random.Random(42).shuffle(paws_rows)
    paws_rows = paws_rows[:500]
    gold_matrix = _matrix(gold, "gold")
    paws_matrix = _matrix(paws_rows, "paws")
    positions = {id(pair): index for index, pair in enumerate(gold)}
    records: list[dict[str, Any]] = []
    transfer: list[dict[str, Any]] = []
    risk: list[dict[str, Any]] = []
    risk_candidates: list[dict[str, Any]] = []
    error_candidates: list[dict[str, Any]] = []
    split_rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        splits = group_split(gold, seed, fractions=GOLD_SPLIT_FRACTIONS)
        train, val, cal, test = (splits[name] for name in ("train", "val", "cal", "test"))
        split_rows.append(
            {
                "seed": seed,
                **{f"{name}_n": len(rows) for name, rows in splits.items()},
                **{
                    f"{name}_positive": sum(bool(pair.answer_reusable) for pair in rows)
                    for name, rows in splits.items()
                },
                "label_type": "gold_answer_match",
            }
        )
        x_train, x_val, x_cal, x_test = (
            _part(gold_matrix, positions, splits[name]) for name in ("train", "val", "cal", "test")
        )
        val_labels = _labels(val, gold=True)
        static_threshold = _choose_f1(x_val[:, 0], val_labels, THRESHOLDS)
        # Preserve the historical capitalization baseline for reproducible prior CSVs.
        heuristic = CachePolicy(
            use_adaptive=True, use_verifier=True, verifier_mode="capitalization"
        )
        for source, rows, matrix, destination in (
            ("nq_open", test, x_test, records),
            ("paws", paws_rows, paws_matrix, transfer),
        ):
            destination.append(
                _record(
                    rows,
                    matrix[:, 0],
                    static_threshold,
                    seed=seed,
                    system="static_val_f1",
                    source=source,
                )
            )
            if source == "nq_open":
                error_candidates.extend(
                    _false_accepts(
                        rows,
                        matrix[:, 0],
                        static_threshold,
                        seed=seed,
                        policy="static_val_f1",
                        metadata=gold_metadata,
                    )
                )
            decisions = [
                heuristic.decide(pair.incoming_query, pair.stored_query, float(matrix[i, 0]), 0.0)[
                    0
                ]
                for i, pair in enumerate(rows)
            ]
            destination.append(
                _record(
                    rows,
                    np.asarray(decisions, dtype=np.float64),
                    0.5,
                    seed=seed,
                    system="adaptive_tier1",
                    source=source,
                )
            )
            if source == "nq_open":
                error_candidates.extend(
                    _false_accepts(
                        rows,
                        np.asarray(decisions, dtype=np.float64),
                        0.5,
                        seed=seed,
                        policy="adaptive_tier1",
                        metadata=gold_metadata,
                    )
                )
        for name in MODEL_NAMES:
            columns = slice(None) if name == "learned_with_nli" else slice(None, -2)
            scaler = StandardScaler().fit(x_train[:, columns])
            model = LogisticRegression(max_iter=1000, random_state=seed).fit(
                scaler.transform(x_train[:, columns]), _labels(train, gold=True)
            )
            raw_val = model.predict_proba(scaler.transform(x_val[:, columns]))[:, 1]
            calibrator = IsotonicRegression(out_of_bounds="clip").fit(raw_val, val_labels)

            val_scores = _predict(x_val, columns, scaler, model, calibrator)
            threshold = _choose_f1(val_scores, val_labels, tuple(sorted(set(val_scores))))
            for source, rows, matrix, destination in (
                ("nq_open", test, x_test, records),
                ("paws", paws_rows, paws_matrix, transfer),
            ):
                scores = _predict(matrix, columns, scaler, model, calibrator)
                destination.append(
                    _record(
                        rows,
                        scores,
                        threshold,
                        seed=seed,
                        system=name,
                        source=source,
                    )
                )
                if source == "nq_open" and name == "learned_with_nli":
                    error_candidates.extend(
                        _false_accepts(
                            rows,
                            scores,
                            threshold,
                            seed=seed,
                            policy=name,
                            metadata=gold_metadata,
                        )
                    )
            if name != "learned_with_nli" or not include_risk:
                continue
            calibration_scores = _predict(x_cal, columns, scaler, model, calibrator)
            test_scores = _predict(x_test, columns, scaler, model, calibrator)
            calibration_labels = _labels(cal, gold=True)
            alpha = 0.05 / len(RISK_GRID)
            for cutoff in RISK_GRID:
                chosen = calibration_scores >= cutoff
                accepted = int(chosen.sum())
                errors = int((chosen & (calibration_labels == 0)).sum())
                risk_candidates.append(
                    {
                        "seed": seed,
                        "threshold": cutoff,
                        "calibration_n": len(cal),
                        "calibration_accepted": accepted,
                        "calibration_errors": errors,
                        "upper_bound": binomial_upper(errors, accepted, alpha)
                        if accepted
                        else None,
                        "test_coverage_at_threshold": float((test_scores >= cutoff).mean()),
                        "label_type": "gold_answer_match",
                    }
                )
            for epsilon in TARGETS:
                selection = select_threshold(
                    cast(list[float], calibration_scores.tolist()),
                    [bool(value) for value in calibration_labels],
                    list(RISK_GRID),
                    epsilon=epsilon,
                    delta=0.05,
                )
                selected = test_scores >= selection.threshold
                labels = _labels(test, gold=True)
                accepted = int(selected.sum())
                errors = int((selected & (labels == 0)).sum())
                risk.append(
                    {
                        "seed": seed,
                        "epsilon": epsilon,
                        "threshold": selection.threshold,
                        "calibration_n": len(cal),
                        "calibration_accepted": selection.accepted,
                        "calibration_errors": selection.errors,
                        "upper_bound": selection.upper_bound,
                        "test_n": len(test),
                        "test_accepted": accepted,
                        "test_errors": errors,
                        "test_risk_among_served": errors / accepted if accepted else None,
                        "test_coverage": accepted / len(test),
                        "label_type": "gold_answer_match",
                    }
                )
    RESULTS.mkdir(exist_ok=True)
    _write(RESULTS / "gold_model.csv", records)
    _write(RESULTS / "gold_paws_transfer.csv", transfer)
    _write(RESULTS / "gold_split_sizes.csv", split_rows)
    _write(RESULTS / "false_accepts.csv", _sample_false_accepts(error_candidates))
    if include_risk:
        _write(RESULTS / "gold_risk.csv", risk)
        _write(RESULTS / "gold_risk_candidates.csv", risk_candidates)
        minimum_rows = []
        for epsilon in TARGETS:
            minimum = math.ceil(math.log(alpha) / math.log1p(-epsilon))
            while binomial_upper(0, minimum, alpha) > epsilon:
                minimum += 1
            while minimum > 1 and binomial_upper(0, minimum - 1, alpha) <= epsilon:
                minimum -= 1
            minimum_rows.append(
                {
                    "epsilon": epsilon,
                    "delta": 0.05,
                    "grid_size": len(RISK_GRID),
                    "per_threshold_alpha": alpha,
                    "minimum_accepted_if_zero_errors": minimum,
                }
            )
        _write(RESULTS / "gold_risk_min_samples.csv", minimum_rows)
    (RESULTS / "gold_model_manifest.json").write_text(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(GOLD.read_bytes()).hexdigest(),
                "embedding_model": get_settings().embedding_model,
                "embedding_revision": get_settings().embedding_revision,
                "nli_model": get_settings().nli_model,
                "nli_revision": get_settings().nli_revision,
                "feature_names": list(NLI_FEATURE_NAMES),
                "seeds": list(SEEDS),
                "risk_grid": list(RISK_GRID),
                "split_fractions": list(GOLD_SPLIT_FRACTIONS),
                "label_type": "gold_answer_match",
                "deployable": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {len(records)} gold rows and {len(transfer)} PAWS transfer rows")
    if include_risk:
        print(f"Wrote {len(risk)} risk rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--risk", action="store_true", help="Run step 2 risk selection")
    run(include_risk=parser.parse_args().risk)
