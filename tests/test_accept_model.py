"""Artifact integrity and feature checks stay offline."""

import hashlib
import json
import math
from pathlib import Path

import pytest

from app.cache.accept_model import FEATURE_NAMES, AcceptModel, features


def _artifact(path: Path, label_type: str) -> None:
    payload = {
        "feature_names": list(FEATURE_NAMES),
        "weights": [0.0] * len(FEATURE_NAMES),
        "intercept": 0.0,
        "means": [0.0] * len(FEATURE_NAMES),
        "scales": [1.0] * len(FEATURE_NAMES),
        "calibration_x": [0.0, 1.0],
        "calibration_y": [0.0, 1.0],
        "label_type": label_type,
    }
    payload["version"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_prefix_reversal_is_a_feature() -> None:
    values = features("How do I uninstall Python?", "How do I install Python?", 0.9, 0.2)
    assert values[FEATURE_NAMES.index("prefix_polarity_mismatch")] == 1.0
    with pytest.raises(ValueError):
        features("a", "b", math.nan, 0.0)


def test_proxy_artifact_cannot_be_deployed(tmp_path: Path) -> None:
    path = tmp_path / "proxy.json"
    _artifact(path, "query_pair_proxy")
    with pytest.raises(ValueError, match="independently reviewed"):
        AcceptModel.load(path)
    assert AcceptModel.load(path, allow_proxy_for_research=True).probability(
        (0.0,) * len(FEATURE_NAMES)
    ) == pytest.approx(0.5)


def test_tampered_artifact_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "reviewed.json"
    _artifact(path, "reviewed_answer_reuse")
    content = json.loads(path.read_text(encoding="utf-8"))
    content["intercept"] = 100
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        AcceptModel.load(path)
