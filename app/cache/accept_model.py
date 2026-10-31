"""Small interpretable accept scorer; only reviewed answer-label artifacts are deployable."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from ..embeddings import tokenize
from .verifier import _entities, _negation_flag, _numbers

FEATURE_NAMES = (
    "cosine",
    "token_jaccard",
    "length_ratio",
    "number_mismatch",
    "negation_mismatch",
    "entity_mismatch",
    "prefix_polarity_mismatch",
    "density",
    "answer_token_overlap",
)
_PREFIX_PAIRS = (("install", "uninstall"), ("enable", "disable"), ("lock", "unlock"))


def features(
    incoming: str,
    stored: str,
    similarity: float,
    density: float,
    cached_answer: str = "",
) -> tuple[float, ...]:
    """Inference-time features only; no labels or future cache state."""
    if not math.isfinite(similarity) or not math.isfinite(density) or not 0 <= density <= 1:
        raise ValueError("Invalid similarity or density")
    incoming_tokens, stored_tokens = set(tokenize(incoming)), set(tokenize(stored))
    union = incoming_tokens | stored_tokens
    jaccard = len(incoming_tokens & stored_tokens) / len(union) if union else 0.0
    lengths = (len(incoming_tokens), len(stored_tokens))
    length_ratio = min(lengths) / max(lengths) if max(lengths) else 0.0
    prefix_mismatch = any(
        (a in incoming_tokens and b in stored_tokens)
        or (b in incoming_tokens and a in stored_tokens)
        for a, b in _PREFIX_PAIRS
    )
    answer_tokens = set(tokenize(cached_answer))
    answer_overlap = (
        len(incoming_tokens & answer_tokens) / len(incoming_tokens) if incoming_tokens else 0.0
    )
    return (
        similarity,
        jaccard,
        length_ratio,
        float(_numbers(incoming) != _numbers(stored)),
        float(_negation_flag(incoming) != _negation_flag(stored)),
        float(_entities(incoming) != _entities(stored)),
        float(prefix_mismatch),
        density,
        answer_overlap,
    )


@dataclass(frozen=True, slots=True)
class AcceptModel:
    weights: tuple[float, ...]
    intercept: float
    means: tuple[float, ...]
    scales: tuple[float, ...]
    calibration_x: tuple[float, ...]
    calibration_y: tuple[float, ...]
    label_type: str
    version: str

    @classmethod
    def load(cls, path: Path, *, allow_proxy_for_research: bool = False) -> AcceptModel:
        raw = json.loads(path.read_text(encoding="utf-8"))
        version = raw.pop("version")
        calculated = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        if version != calculated:
            raise ValueError("Model artifact hash mismatch")
        if raw.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError("Incompatible accept-model features")
        label_type = raw["label_type"]
        if label_type != "reviewed_answer_reuse" and not allow_proxy_for_research:
            raise ValueError("Only independently reviewed answer-reuse models may be deployed")
        weights = tuple(float(x) for x in raw["weights"])
        intercept = float(raw["intercept"])
        means = tuple(float(x) for x in raw["means"])
        scales = tuple(float(x) for x in raw["scales"])
        xs = tuple(float(x) for x in raw["calibration_x"])
        ys = tuple(float(x) for x in raw["calibration_y"])
        if not all(len(items) == len(FEATURE_NAMES) for items in (weights, means, scales)):
            raise ValueError("Invalid model vector length")
        if not xs or len(xs) != len(ys) or sorted(xs) != list(xs):
            raise ValueError("Invalid calibration curve")
        if any(not math.isfinite(x) for x in (intercept, *weights, *means, *scales, *xs, *ys)):
            raise ValueError("Nonfinite model artifact")
        if any(scale <= 0 for scale in scales) or any(not 0 <= y <= 1 for y in ys):
            raise ValueError("Invalid model scale or calibration probability")
        return cls(weights, intercept, means, scales, xs, ys, label_type, version)

    def probability(self, values: tuple[float, ...]) -> float:
        if len(values) != len(FEATURE_NAMES) or any(not math.isfinite(x) for x in values):
            raise ValueError("Invalid accept-model features")
        logit = self.intercept + sum(
            weight * (value - mean) / scale
            for value, weight, mean, scale in zip(
                values, self.weights, self.means, self.scales, strict=True
            )
        )
        raw = 1 / (1 + math.exp(-max(-60.0, min(60.0, logit))))
        index = bisect.bisect_left(self.calibration_x, raw)
        if index == 0:
            return self.calibration_y[0]
        if index == len(self.calibration_x):
            return self.calibration_y[-1]
        left_x, right_x = self.calibration_x[index - 1], self.calibration_x[index]
        left_y, right_y = self.calibration_y[index - 1], self.calibration_y[index]
        fraction = (raw - left_x) / (right_x - left_x) if right_x > left_x else 0.0
        return left_y + fraction * (right_y - left_y)
