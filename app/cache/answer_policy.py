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
from .subject_identity import conflicting_named_work
from .verifier import NliVerifier, _negation_flag, _numbers

Action = Literal["ACCEPT", "VERIFY", "REJECT"]
_COSINE_ROUNDING_TOLERANCE = 0.0001
_MIN_ANSWER_CHARS_FOR_MENTION = 3
_SCOPE_ALIASES = {
    "first": "first",
    "earliest": "first",
    "inaugural": "first",
    "last": "last",
    "final": "last",
    "only": "only",
    "sole": "only",
    "most": "most",
    "maximum": "most",
    "least": "least",
    "minimum": "least",
}


def _scope_terms(tokens: list[str]) -> set[str]:
    return {
        _SCOPE_ALIASES[token]
        for index, token in enumerate(tokens)
        if token in _SCOPE_ALIASES and not (token == "final" and index == len(tokens) - 1)
    }


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

    def decide(  # noqa: PLR0911, PLR0912, PLR0913, PLR0917 - shared live/replay decision
        self,
        incoming: str,
        stored: str,
        answer: str,
        similarity: float,
        verifier: NliVerifier,
        subject_guard: bool = True,
    ) -> AnswerDecision:
        if (
            not answer.strip()
            or not math.isfinite(similarity)
            or abs(similarity) > 1 + _COSINE_ROUNDING_TOLERANCE
        ):
            return AnswerDecision("REJECT", "invalid_candidate", None)
        # Normalized float32 dot products can overshoot one by a few ULPs.
        similarity = max(-1.0, min(1.0, similarity))
        if similarity < self.min_similarity:
            return AnswerDecision("REJECT", "below_retrieval_threshold", None)
        if _numbers(incoming) != _numbers(stored):
            return AnswerDecision("REJECT", "number_mismatch", None)
        if _negation_flag(incoming) != _negation_flag(stored):
            return AnswerDecision("REJECT", "negation_mismatch", None)
        if subject_guard and conflicting_named_work(incoming, stored):
            return AnswerDecision("REJECT", "subject_identity_conflict", None)
        incoming_tokens, stored_tokens = tokenize(incoming), tokenize(stored)
        answer_tokens = tokenize(answer)
        # A proposed answer repeated in the new question may play a different
        # grammatical role (e.g. an object becoming the subject). Abstain.
        if (
            incoming_tokens != stored_tokens
            and answer_tokens
            and len("".join(answer_tokens)) >= _MIN_ANSWER_CHARS_FOR_MENTION
        ):
            width = len(answer_tokens)
            if any(
                incoming_tokens[index : index + width] == answer_tokens
                for index in range(len(incoming_tokens) - width + 1)
            ):
                return AnswerDecision("VERIFY", "answer_mentioned_in_question", None)
        # A fact scoped by an ordinal/superlative is not automatically a complete
        # answer to an unscoped question, or the reverse.
        if _scope_terms(incoming_tokens) != _scope_terms(stored_tokens):
            return AnswerDecision("VERIFY", "scope_changed", None)
        yes_no_openers = {"is", "are", "was", "were", "do", "does", "did", "can", "has"}
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
        assess = getattr(verifier, "assess", None)
        if assess is not None:
            assessment = assess(premise, hypothesis)
            if assessment.status == "too_long":
                return AnswerDecision("VERIFY", "context_too_long", None)
            score = assessment.score
        else:
            score = verifier.entail_prob(premise, hypothesis)
        if score is None or not math.isfinite(score):
            return AnswerDecision("VERIFY", "verifier_unavailable", None)
        if score >= self.accept_at:
            return AnswerDecision("ACCEPT", "answer_entailment", score)
        if score < self.reject_below:
            return AnswerDecision("REJECT", "answer_contradiction_or_irrelevance", score)
        return AnswerDecision("VERIFY", "uncertain_answer", score)
