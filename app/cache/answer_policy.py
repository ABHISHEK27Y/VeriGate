"""Opt-in answer-aware cache decisions shared by the gateway and replay.

VERIFY means ask the upstream provider; it never serves the candidate answer.
The NLI model estimates compatibility of two answer assertions, not factual truth.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..embeddings import tokenize
from .verifier import NliVerifier, _negation_flag, _numbers

Action = Literal["ACCEPT", "VERIFY", "REJECT"]


@dataclass(frozen=True)
class AnswerDecision:
    action: Action
    reason: str
    score: float | None


@dataclass(frozen=True)
class AnswerPolicy:
    model: str
    revision: str
    accept_at: float
    reject_below: float
    min_similarity: float
    version: str
    ambiguity_terms: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> AnswerPolicy:
        raw = json.loads(path.read_text(encoding="utf-8"))
        version = raw.pop("version")
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        if version != digest or raw.get("schema_version") != "answer-policy-v1":
            raise ValueError("Invalid answer-policy artifact")
        accept, reject = float(raw["accept_at"]), float(raw["reject_below"])
        minimum = float(raw["min_similarity"])
        if not (math.isfinite(accept) and math.isfinite(reject) and 0 <= reject < accept <= 1):
            raise ValueError("Invalid answer-policy thresholds")
        if not math.isfinite(minimum) or not 0 <= minimum <= 1:
            raise ValueError("Invalid answer-policy retrieval threshold")
        if not raw["model"] or not raw["revision"]:
            raise ValueError("Answer policy requires a pinned model")
        terms = tuple(str(term).casefold() for term in raw["ambiguity_terms"])
        return cls(raw["model"], raw["revision"], accept, reject, minimum, version, terms)

    def decide(  # noqa: PLR0911 - distinct fail-closed outcomes
        self,
        incoming: str,
        stored: str,
        answer: str,
        similarity: float,
        verifier: NliVerifier,
    ) -> AnswerDecision:
        if not answer.strip() or not math.isfinite(similarity) or not -1 <= similarity <= 1:
            return AnswerDecision("REJECT", "invalid_candidate", None)
        if similarity < self.min_similarity:
            return AnswerDecision("REJECT", "below_retrieval_threshold", None)
        if _numbers(incoming) != _numbers(stored):
            return AnswerDecision("REJECT", "number_mismatch", None)
        if _negation_flag(incoming) != _negation_flag(stored):
            return AnswerDecision("REJECT", "negation_mismatch", None)
        yes_no_openers = {"is", "are", "was", "were", "do", "does", "did", "can", "has"}
        incoming_tokens, stored_tokens = tokenize(incoming), tokenize(stored)
        if (
            incoming_tokens
            and incoming_tokens[0] in yes_no_openers
            and (not stored_tokens or stored_tokens[0] not in yes_no_openers)
        ):
            return AnswerDecision("REJECT", "answer_type_mismatch", None)
        text = f"{incoming} {stored}".casefold()
        if any(term in text for term in self.ambiguity_terms):
            return AnswerDecision("VERIFY", "ambiguous_context", None)
        premise = f"The answer to {stored} is {answer}."
        hypothesis = f"The answer to {incoming} is {answer}."
        score = verifier.entail_prob(premise, hypothesis)
        if score is None or not math.isfinite(score):
            return AnswerDecision("VERIFY", "verifier_unavailable", None)
        if score >= self.accept_at:
            return AnswerDecision("ACCEPT", "answer_entailment", score)
        if score < self.reject_below:
            return AnswerDecision("REJECT", "answer_contradiction_or_irrelevance", score)
        return AnswerDecision("VERIFY", "uncertain_answer", score)
