"""Opt-in, versioned three-field answer-reuse classifier.

This adapter is deliberately inactive without a locally trained, calibrated
artifact. Structural checks and the existing NLI policy remain available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..config import get_settings
from .verifier import verifier_scope

log = logging.getLogger("verigate.reuse_verifier")
FORMAT_VERSION = "reuse-three-field-v1"
MAX_MEMO = 8192
MAX_PLAUSIBLE_WINDOW = 100_000


def format_input(stored: str, answer: str, incoming: str) -> tuple[str, str]:
    """Use the same explicit field layout during training and inference."""
    return (f"Stored question: {stored}\nStored answer: {answer}", f"Incoming question: {incoming}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ReuseAssessment:
    score: float | None
    status: Literal["ok", "too_long", "unavailable"]
    input_tokens: int | None


class TaskReuseVerifier:
    """Fail-closed CPU inference from an immutable, hashed local artifact."""

    def __init__(self, manifest_path: Path):
        source = manifest_path.read_bytes()
        raw = json.loads(source)
        if raw.get("format_version") != FORMAT_VERSION:
            raise ValueError("Unsupported reuse verifier format")
        if raw.get("base_model") != "cross-encoder/nli-deberta-v3-xsmall":
            raise ValueError("Unexpected reuse verifier base model")
        if raw.get("base_revision") != get_settings().nli_revision:
            raise ValueError("Unexpected reuse verifier base revision")
        if raw.get("input_format") != "stored-question-and-answer paired with incoming-question":
            raise ValueError("Unexpected reuse verifier input format")
        if not isinstance(raw.get("files"), dict) or not raw["files"]:
            raise ValueError("Reuse verifier lacks file hashes")
        for name, expected in raw["files"].items():
            candidate = (manifest_path.parent / name).resolve()
            if not candidate.is_relative_to(manifest_path.parent.resolve()):
                raise ValueError("Reuse verifier file escapes artifact directory")
            if sha256_file(candidate) != expected:
                raise ValueError(f"Reuse verifier file changed: {name}")
        threshold = float(raw["accept_at"])
        if not math.isfinite(threshold) or not 0 < threshold < 1:
            raise ValueError("Invalid reuse verifier threshold")
        if raw.get("calibration", {}).get("validated") is not True:
            raise ValueError("Reuse verifier calibration did not pass its gate")
        self.identity = hashlib.sha256(source).hexdigest()
        self.path = manifest_path.parent
        self.accept_at = threshold
        self.model: Any = None
        self.tokenizer: Any = None
        self.unavailable = False
        self.prewarmed = False
        self.last_failure_category: str | None = None
        self.lock = threading.Lock()
        self.cache: OrderedDict[tuple[str, str, str, str, str], ReuseAssessment] = OrderedDict()

    def prewarm(self) -> None:
        if self.assess_reuse("Test question", "Test answer", "Test question").status != "ok":
            raise RuntimeError("Task reuse verifier prewarm failed")
        self.prewarmed = True

    def purge_scope(self, scope: str) -> None:
        with self.lock:
            for key in tuple(self.cache):
                if key[1] == scope:
                    del self.cache[key]

    def assess_reuse(self, stored: str, answer: str, incoming: str) -> ReuseAssessment:
        key = (self.identity, verifier_scope.get(), stored, answer, incoming)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            if self.unavailable:
                return ReuseAssessment(None, "unavailable", None)
            try:
                if self.model is None:
                    import torch  # noqa: PLC0415 - optional local model
                    from transformers import (  # noqa: PLC0415 - optional local model
                        AutoModelForSequenceClassification,
                        AutoTokenizer,
                    )

                    self.tokenizer = AutoTokenizer.from_pretrained(self.path, local_files_only=True)
                    self.model = AutoModelForSequenceClassification.from_pretrained(
                        self.path, local_files_only=True
                    ).eval()
                    if self.model.config.num_labels != 1:
                        raise ValueError("Reuse verifier must have one binary logit")  # noqa: TRY301
                    self.model.to("cpu")
                else:
                    import torch  # noqa: PLC0415 - optional local model

                first, second = format_input(stored, answer, incoming)
                encoded = self.tokenizer(first, second, truncation=False, return_tensors="pt")
                count = int(encoded["input_ids"].shape[1])
                limits = (
                    self.model.config.max_position_embeddings,
                    self.tokenizer.model_max_length,
                )
                finite = [
                    int(n) for n in limits if isinstance(n, int) and 0 < n < MAX_PLAUSIBLE_WINDOW
                ]
                if not finite:
                    raise ValueError("No finite reuse verifier context window")  # noqa: TRY301
                if count > min(finite):
                    result = ReuseAssessment(None, "too_long", count)
                else:
                    with torch.inference_mode():
                        logit = self.model(**encoded).logits.reshape(-1)
                    if logit.numel() != 1 or not torch.isfinite(logit).all():
                        raise ValueError("Malformed reuse verifier output")  # noqa: TRY301
                    result = ReuseAssessment(float(torch.sigmoid(logit[0])), "ok", count)
            except Exception as exc:
                log.exception("Task reuse verifier unavailable; abstaining")
                self.unavailable = True
                self.last_failure_category = type(exc).__name__
                return ReuseAssessment(None, "unavailable", None)
            self.cache[key] = result
            if len(self.cache) > MAX_MEMO:
                self.cache.popitem(last=False)
            return result
