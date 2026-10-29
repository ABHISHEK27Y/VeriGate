"""Exploratory learned pair-equivalence models; artifacts cannot authorize answer reuse."""

from __future__ import annotations

import csv
import hashlib
import json
import random

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.cache.accept_model import FEATURE_NAMES, features
from app.cache.policy import CachePolicy
from app.embeddings import cosine
from evaluation.datasets import Pair, group_split, paws, qqp, smoke, stsb
from evaluation.protocol import Decision, bootstrap_ci, metrics
from evaluation.reproduce import ROOT, SEEDS, _vector_cache

FIELDS = (
    "train_source",
    "test_source",
    "seed",
    "system",
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
    "label_type",
)


def _matrix(pairs: list[Pair], vectors: dict[str, np.ndarray]) -> np.ndarray:
    return np.asarray(
        [
            features(
                pair.incoming_query,
                pair.stored_query,
                cosine(vectors[pair.incoming_query], vectors[pair.stored_query]),
                0.0,
            )
            for pair in pairs
        ],
        dtype=np.float64,
    )


def _labels(pairs: list[Pair]) -> np.ndarray:
    return np.asarray([int(pair.equivalent) for pair in pairs], dtype=np.int8)


def _coverage_cutoff(scores: np.ndarray, desired: int) -> float:
    if desired <= 0:
        return float("inf")
    if desired >= len(scores):
        return float("-inf")
    return float(np.sort(scores)[-desired])


def _record(  # noqa: PLR0913 - output records experiment identifiers
    name: str,
    source: str,
    seed: int,
    pairs: list[Pair],
    scores: np.ndarray,
    cutoff: float,
) -> dict[str, str | int | float | None]:
    decisions = [
        Decision(pair.equivalent, float(score), bool(score >= cutoff), pair.source_id)
        for pair, score in zip(pairs, scores, strict=True)
    ]
    result = metrics(decisions)
    risk_low, risk_high = bootstrap_ci(decisions, "false_hit_among_served", seed=seed)
    coverage_low, coverage_high = bootstrap_ci(decisions, "coverage", seed=seed)
    return {
        "train_source": "qqp",
        "test_source": source,
        "seed": seed,
        "system": name,
        **result,
        "risk_ci_low": risk_low,
        "risk_ci_high": risk_high,
        "coverage_ci_low": coverage_low,
        "coverage_ci_high": coverage_high,
        "label_type": "query_pair_proxy",
    }


def _export_proxy_model(
    model: LogisticRegression,
    scaler: StandardScaler,
    calibrator: IsotonicRegression,
) -> None:
    payload = {
        "feature_names": list(FEATURE_NAMES),
        "weights": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "means": scaler.mean_.tolist(),
        "scales": scaler.scale_.tolist(),
        "calibration_x": calibrator.X_thresholds_.tolist(),
        "calibration_y": calibrator.y_thresholds_.tolist(),
        "label_type": "query_pair_proxy",
    }
    payload["version"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    target = ROOT / "evaluation" / "results" / "accept_proxy.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def _part(matrix: np.ndarray, lookup: dict[int, int], rows: list[Pair]) -> np.ndarray:
    return matrix[[lookup[id(row)] for row in rows]]


def run() -> list[dict[str, str | int | float | None]]:
    corpora = {
        "qqp": qqp(ROOT / "data" / "qqp.tsv"),
        "paws": paws(ROOT / "data" / "paws.tsv"),
        "stsb": stsb(ROOT / "data" / "stsb.tsv"),
        "smoke_development_only": smoke(),
    }
    for name in ("qqp", "paws", "stsb"):
        random.Random(42).shuffle(corpora[name])
        corpora[name] = corpora[name][:2000]
    vectors = {name: _vector_cache(rows) for name, rows in corpora.items()}
    matrices = {name: _matrix(rows, vectors[name]) for name, rows in corpora.items()}
    index = {name: {id(row): i for i, row in enumerate(rows)} for name, rows in corpora.items()}
    output: list[dict[str, str | int | float | None]] = []
    for seed in SEEDS:
        splits = group_split(corpora["qqp"], seed)

        train, val, cal = (splits[name] for name in ("train", "val", "cal"))
        x_train, x_val, x_cal = (
            _part(matrices["qqp"], index["qqp"], splits[name]) for name in ("train", "val", "cal")
        )
        scaler = StandardScaler().fit(x_train)
        logistic = LogisticRegression(max_iter=1000, random_state=seed).fit(
            scaler.transform(x_train), _labels(train)
        )
        lexical = LogisticRegression(max_iter=1000, random_state=seed).fit(
            scaler.transform(x_train)[:, :3], _labels(train)
        )
        boosting = HistGradientBoostingClassifier(max_iter=100, random_state=seed).fit(
            x_train, _labels(train)
        )
        models = {
            "logistic_all": (logistic, scaler.transform(x_val), scaler.transform(x_cal)),
            "logistic_lexical": (
                lexical,
                scaler.transform(x_val)[:, :3],
                scaler.transform(x_cal)[:, :3],
            ),
            "gradient_boosting": (boosting, x_val, x_cal),
        }
        heuristic = CachePolicy(use_adaptive=True, use_verifier=True)
        heuristic_cal = sum(
            heuristic.decide(row.incoming_query, row.stored_query, float(x_cal[i, 0]), density=0.0)[
                0
            ]
            for i, row in enumerate(cal)
        )
        calibrators = {}
        cutoffs = {}
        for name, (model, val_x, cal_x) in models.items():
            calibration = IsotonicRegression(out_of_bounds="clip").fit(
                model.predict_proba(val_x)[:, 1], _labels(val)
            )
            calibrated = calibration.predict(model.predict_proba(cal_x)[:, 1])
            cutoffs[name] = _coverage_cutoff(calibrated, heuristic_cal)
            calibrators[name] = calibration
        if seed == SEEDS[0]:
            _export_proxy_model(logistic, scaler, calibrators["logistic_all"])
        for source, corpus_rows in corpora.items():
            if source == "qqp":
                test_rows = splits["test"]
                x_test = _part(matrices["qqp"], index["qqp"], test_rows)
            else:
                test_rows = corpus_rows
                x_test = matrices[source]
            for name, (model, _, _) in models.items():
                selected = (
                    scaler.transform(x_test)[:, :3]
                    if name == "logistic_lexical"
                    else scaler.transform(x_test)
                    if name == "logistic_all"
                    else x_test
                )
                score = calibrators[name].predict(model.predict_proba(selected)[:, 1])
                output.append(_record(name, source, seed, test_rows, score, cutoffs[name]))
    result_dir = ROOT / "evaluation" / "results"
    result_dir.mkdir(exist_ok=True)
    with (result_dir / "learned_transfer.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output)
    return output


if __name__ == "__main__":
    rows = run()
    print(f"Wrote {len(rows)} query-pair proxy rows; no answer-level model is deployable.")
