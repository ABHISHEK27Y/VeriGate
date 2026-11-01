"""Five-seed strict/lenient gold-label comparison of cache verifiers and policies."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.cache.policy import CachePolicy
from app.cache.verifier import VerifierMode
from app.embeddings import active_backend
from evaluation.datasets import Pair, group_split
from evaluation.gold_answers import lenient_reuse_ok, load_pairs
from evaluation.gold_model import (
    GOLD,
    GOLD_SPLIT_FRACTIONS,
    MODEL_NAMES,
    RESULTS,
    _choose_f1,
    _gold_metadata,
    _matrix,
    _part,
    _predict,
    _question_component_ids,
    _write,
)
from evaluation.protocol import Decision, bootstrap_ci, metrics
from evaluation.reproduce import SEEDS, THRESHOLDS


def _labels(rows: list[Pair], rule: str, lenient: dict[str, bool]) -> np.ndarray:
    return np.asarray(
        [
            int(bool(row.answer_reusable) if rule == "strict" else lenient[row.source_id])
            for row in rows
        ],
        dtype=np.int8,
    )


def _record(  # noqa: PLR0913 - all fields identify the held-out evaluation
    pairs: list[Pair],
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: float,
    *,
    rule: str,
    seed: int,
    system: str,
) -> dict[str, Any]:
    groups = _question_component_ids(pairs)
    decisions = [
        Decision(bool(label), float(score), bool(score >= threshold), group)
        for label, score, group in zip(labels, scores, groups, strict=True)
    ]
    risk_low, risk_high = bootstrap_ci(decisions, "false_hit_among_served", seed=seed)
    coverage_low, coverage_high = bootstrap_ci(decisions, "coverage", seed=seed)
    return {
        "label_rule": rule,
        "label_type": f"gold_answer_match_{rule}",
        "seed": seed,
        "system": system,
        "chosen_threshold": threshold,
        **metrics(decisions),
        "risk_ci_low": risk_low,
        "risk_ci_high": risk_high,
        "coverage_ci_low": coverage_low,
        "coverage_ci_high": coverage_high,
    }


def _lenient_map() -> dict[str, bool]:
    result = {}
    for key, row in _gold_metadata().items():
        stored = json.loads(row["stored_aliases"])
        incoming = json.loads(row["incoming_aliases"])
        result[key] = lenient_reuse_ok(stored, incoming)
    return result


def run() -> None:  # noqa: PLR0915 - parallel policies share the same split state
    if active_backend() != "minilm":
        raise ValueError("Gold verifier study requires pinned MiniLM embeddings")
    gold, _ = load_pairs(GOLD)
    lenient = _lenient_map()
    matrix = _matrix(gold, "gold")
    positions = {id(pair): index for index, pair in enumerate(gold)}
    records: list[dict[str, Any]] = []
    label_counts: list[dict[str, Any]] = []
    for seed in SEEDS:
        splits = group_split(gold, seed, fractions=GOLD_SPLIT_FRACTIONS)
        train, val, cal, test = (splits[name] for name in ("train", "val", "cal", "test"))
        x_train, x_val, x_test = (
            _part(matrix, positions, splits[name]) for name in ("train", "val", "test")
        )
        for rule in ("strict", "lenient"):
            train_labels = _labels(train, rule, lenient)
            val_labels = _labels(val, rule, lenient)
            test_labels = _labels(test, rule, lenient)
            label_counts.append(
                {
                    "seed": seed,
                    "label_rule": rule,
                    "label_type": f"gold_answer_match_{rule}",
                    "corpus_n": len(gold),
                    "corpus_positive": sum(
                        bool(pair.answer_reusable) if rule == "strict" else lenient[pair.source_id]
                        for pair in gold
                    ),
                    "train_n": len(train),
                    "train_positive": int(train_labels.sum()),
                    "val_n": len(val),
                    "val_positive": int(val_labels.sum()),
                    "cal_n": len(cal),
                    "cal_positive": int(_labels(cal, rule, lenient).sum()),
                    "test_n": len(test),
                    "test_positive": int(test_labels.sum()),
                }
            )
            static_threshold = _choose_f1(x_val[:, 0], val_labels, THRESHOLDS)
            records.append(
                _record(
                    test,
                    test_labels,
                    x_test[:, 0],
                    static_threshold,
                    rule=rule,
                    seed=seed,
                    system="static_val_f1",
                )
            )
            verifier_variants: tuple[tuple[VerifierMode, str], ...] = (
                ("capitalization", "adaptive_capitalization"),
                ("token_diff", "adaptive_token_diff"),
            )
            for mode, system in verifier_variants:
                policy = CachePolicy(use_adaptive=True, use_verifier=True, verifier_mode=mode)
                decisions = np.asarray(
                    [
                        policy.decide(pair.incoming_query, pair.stored_query, float(x_test[i, 0]))[
                            0
                        ]
                        for i, pair in enumerate(test)
                    ],
                    dtype=np.float64,
                )
                records.append(
                    _record(
                        test,
                        test_labels,
                        decisions,
                        0.5,
                        rule=rule,
                        seed=seed,
                        system=system,
                    )
                )
            for name in MODEL_NAMES:
                columns = slice(None) if name == "learned_with_nli" else slice(None, -2)
                scaler = StandardScaler().fit(x_train[:, columns])
                model = LogisticRegression(max_iter=1000, random_state=seed).fit(
                    scaler.transform(x_train[:, columns]), train_labels
                )
                raw_val = model.predict_proba(scaler.transform(x_val[:, columns]))[:, 1]
                calibrator = IsotonicRegression(out_of_bounds="clip").fit(raw_val, val_labels)
                val_scores = _predict(x_val, columns, scaler, model, calibrator)
                threshold = _choose_f1(val_scores, val_labels, tuple(sorted(set(val_scores))))
                scores = _predict(x_test, columns, scaler, model, calibrator)
                records.append(
                    _record(
                        test,
                        test_labels,
                        scores,
                        threshold,
                        rule=rule,
                        seed=seed,
                        system=name,
                    )
                )
    RESULTS.mkdir(exist_ok=True)
    _write(RESULTS / "gold_verifier_policies.csv", records)
    _write(RESULTS / "gold_label_rules.csv", label_counts)
    print(f"Wrote {len(records)} policy rows and {len(label_counts)} label-count rows")


if __name__ == "__main__":
    run()
