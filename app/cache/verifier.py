"""Query-only structural and optional NLI filters for semantic-cache candidates.

Before serving a candidate cached answer (one that already cleared the similarity
threshold), filter some known mismatches WITHOUT calling the upstream LLM.
Tier-1 symbolic checks cover these failure modes:

  - numbers/quantities must match     ("5 GB"  vs "50 GB")
  - negation/polarity must match      ("is X safe" vs "is X NOT safe")
  - changed content and role tokens must match, regardless of capitalization

The token-diff check is conservative: it can reject valid paraphrases. The old
capitalization check remains available as an explicit research ablation.

When enabled, Tier-2 runs NLI after the structural checks for every surviving
candidate. It is not an uncertainty-routed verifier and it does not inspect the
stored answer.

These checks can reject valid paraphrases and accept incompatible cached answers.
"""

from __future__ import annotations

import functools
import logging
import re
import threading
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

import numpy as np

from ..config import get_settings
from ..embeddings import tokenize
from ..metrics import STAGE_LATENCY

_MAX_NLI_PAIRS = 8192
_MAX_PLAUSIBLE_MODEL_WINDOW = 100_000
verifier_scope: ContextVar[str] = ContextVar("verifier_scope", default="standalone")

log = logging.getLogger("verigate.verifier")

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_NEGATIONS = {"not", "no", "never", "without", "cannot", "cant", "dont", "doesnt", "isnt"}
# Common words that are capitalized as sentence-starters, not because they're entities.
_NON_ENTITY_CAPS = {
    "what",
    "how",
    "when",
    "where",
    "why",
    "who",
    "which",
    "is",
    "are",
    "do",
    "does",
    "can",
    "could",
    "would",
    "should",
    "tell",
    "give",
    "list",
    "explain",
    "the",
    "a",
    "an",
    "please",
    "i",
    "my",
    "me",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z]+")
VerifierMode = Literal["token_diff", "capitalization"]
_QUESTION_WORDS = {"who", "what", "which", "when", "where", "why", "how"}
_FUNCTION_WORDS = {
    "a",
    "an",
    "the",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "from",
    "by",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "will",
    "has",
    "have",
    "had",
    "i",
    "me",
    "my",
    "you",
    "your",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "please",
    "tell",
    "give",
    "list",
    *_QUESTION_WORDS,
}
_MEANINGFUL_FUNCTION_WORDS = {
    "is",
    "are",
    "was",
    "were",
    "will",
    "would",
    "can",
    "could",
    "has",
    "had",
    "before",
    "after",
    "from",
    "to",
    "by",
    "for",
    "my",
    "your",
    "his",
    "her",
    "their",
    "all",
    "only",
    "each",
    "any",
    "first",
    "last",
}
_ROLE_WORDS = {
    "directed",
    "wrote",
    "written",
    "produced",
    "created",
    "sang",
    "composed",
    "invented",
    "founded",
    "painted",
    "designed",
    "played",
    "portrayed",
    "won",
    "lost",
    "born",
    "died",
    "built",
    "discovered",
    "first",
    "last",
    "most",
    "least",
    "before",
    "after",
    "highest",
    "lowest",
    "author",
    "director",
    "actor",
    "winner",
}
_ANSWER_TYPE_HINTS = {
    "year": "date",
    "date": "date",
    "month": "date",
    "day": "date",
    "city": "location",
    "country": "location",
    "place": "location",
    "capital": "location",
    "person": "person",
    "name": "person",
    "author": "person",
    "director": "person",
    "number": "quantity",
    "amount": "quantity",
    "price": "quantity",
}


def _answer_type(text: str) -> str | None:  # noqa: PLR0911 - explicit question classes
    tokens = tokenize(text)
    if not tokens:
        return None
    first = next((token for token in tokens[:4] if token in _QUESTION_WORDS), None)
    if first == "who":
        return "person"
    if first == "when":
        return "date"
    if first == "where":
        return "location"
    if first == "why":
        return "reason"
    if first == "how":
        if "many" in tokens[:4] or "much" in tokens[:4]:
            return "quantity"
        if "long" in tokens[:4]:
            return "duration"
        return "method"
    if first in {"what", "which"}:
        return next(
            (_ANSWER_TYPE_HINTS[token] for token in tokens[:6] if token in _ANSWER_TYPE_HINTS),
            "object",
        )
    return None


def _token_diff_reason(first: str, second: str) -> str | None:
    left, right = tokenize(first), tokenize(second)
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        changed_tokens = set(left[i1:i2] + right[j1:j2])
        if changed_tokens & _MEANINGFUL_FUNCTION_WORDS:
            return "scope_or_tense_mismatch"
        changed = changed_tokens - _FUNCTION_WORDS
        if changed & _ROLE_WORDS:
            return "role_mismatch"
        if changed:
            return "content_token_mismatch"
    return None


def _numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _negation_flag(text: str) -> bool:
    normalized = text.lower().replace("\u2019", "'").replace("'", "")
    return bool(set(tokenize(normalized)) & _NEGATIONS)


def _entities(text: str) -> set[str]:
    """Historical capitalization-based proper-noun proxy for ablation only."""
    words = _WORD_RE.findall(text)
    ents = set()
    for w in words:
        if w[0].isupper() and w.lower() not in _NON_ENTITY_CAPS:
            ents.add(w.lower())
    return ents


# ---------------------------------------------------------------------------
# Tier-2: lightweight NLI cross-encoder for semantic equivalence.
#
# Tier-1 catches STRUCTURAL differences (numbers/negation/entities). It cannot tell
# "reset my password" from "reset my router" -- no number/entity/negation differs, yet the
# answers differ. Tier-2 checks *bidirectional entailment* with a small NLI model: the two
# queries are equivalent only if each entails the other. Runs only on candidate hits that
# already passed Tier-1, and results are cached per pair (independent of threshold), so the
# overhead is paid at most once per distinct pair.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NliAssessment:
    score: float | None
    status: Literal["ok", "too_long", "unavailable"]
    input_tokens: int | None


class NliVerifier:
    """Application-owned lazy model with a bounded pair cache."""

    def __init__(self):
        self.model = None
        self.unavailable = False
        self.lock = threading.Lock()
        self.cache: OrderedDict[tuple[str, str, str], NliAssessment] = OrderedDict()

    def prewarm(self) -> None:
        """Load and run the pinned model before readiness when configured."""
        result = self.assess("A short test answer is available.", "A test answer is available.")
        if result.status != "ok":
            raise RuntimeError("Pinned NLI model failed startup prewarm")

    def assess(self, premise: str, hypothesis: str) -> NliAssessment:
        """Score only when the complete paired input fits the model window."""
        key = (verifier_scope.get(), premise, hypothesis)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            if self.unavailable:
                return NliAssessment(None, "unavailable", None)
            try:
                if self.model is None:
                    from sentence_transformers import (  # noqa: PLC0415 - lazy ML dependency
                        CrossEncoder,  # noqa: PLC0415 - lazy ML dependency
                    )

                    started = time.perf_counter()
                    self.model = CrossEncoder(
                        get_settings().nli_model, revision=get_settings().nli_revision or None
                    )
                    STAGE_LATENCY.labels(stage="nli_model_load").observe(
                        time.perf_counter() - started
                    )
                started = time.perf_counter()
                tokenized = self.model.tokenizer(
                    premise, hypothesis, truncation=False, add_special_tokens=True
                )
                count = len(tokenized["input_ids"])
                STAGE_LATENCY.labels(stage="nli_tokenization").observe(
                    time.perf_counter() - started
                )
                limits = (
                    self.model.max_seq_length,
                    self.model.tokenizer.model_max_length,
                    self.model.model.config.max_position_embeddings,
                )
                valid_limits = [
                    int(limit)
                    for limit in limits
                    if isinstance(limit, int) and 0 < limit < _MAX_PLAUSIBLE_MODEL_WINDOW
                ]
                if not valid_limits:
                    raise ValueError("NLI model has no finite input length")  # noqa: TRY301
                if count > min(valid_limits):
                    return NliAssessment(None, "too_long", count)
                started = time.perf_counter()
                logits = np.asarray(self.model.predict([(premise, hypothesis)])).reshape(-1)
                STAGE_LATENCY.labels(stage="nli_inference").observe(time.perf_counter() - started)
                labels = self.model.model.config.id2label
                entail = next(
                    (int(i) for i, label in labels.items() if "entail" in label.lower()), None
                )
                if entail is None:
                    raise ValueError("NLI model must identify its entailment label")  # noqa: TRY301
                probs = np.exp(logits - logits.max())
                result = NliAssessment(float(probs[entail] / probs.sum()), "ok", count)
            except Exception:
                log.exception("NLI unavailable; rejecting semantic reuse")
                self.unavailable = True
                return NliAssessment(None, "unavailable", None)
            self.cache[key] = result
            if len(self.cache) > _MAX_NLI_PAIRS:
                self.cache.popitem(last=False)
            return result

    def entail_prob(self, premise: str, hypothesis: str) -> float | None:
        return self.assess(premise, hypothesis).score

    def equivalent(self, q1: str, q2: str) -> bool | None:
        e1, e2 = self.entail_prob(q1, q2), self.entail_prob(q2, q1)
        if e1 is None or e2 is None:
            return None
        return e1 >= get_settings().nli_threshold and e2 >= get_settings().nli_threshold


@functools.lru_cache(maxsize=1)
def default_verifier() -> NliVerifier:
    """Standalone tooling helper; application policies own a separate verifier."""
    return NliVerifier()


def nli_equivalent(q1: str, q2: str) -> bool | None:
    return default_verifier().equivalent(q1, q2)


def verify_equivalent(  # noqa: PLR0911 - fail-closed reasons are distinct
    q_new: str,
    q_cached: str,
    use_nli: bool = False,
    verifier: NliVerifier | None = None,
    *,
    mode: VerifierMode = "token_diff",
) -> tuple[bool, str]:
    """Return (is_equivalent, reason). Tier-1 always; Tier-2 (NLI) when use_nli=True."""
    # --- Tier 1: structural checks ---
    if _numbers(q_new) != _numbers(q_cached):
        return False, "number_mismatch"
    if _negation_flag(q_new) != _negation_flag(q_cached):
        return False, "negation_mismatch"
    if mode == "token_diff":
        first_type, second_type = _answer_type(q_new), _answer_type(q_cached)
        if first_type is not None and second_type is not None and first_type != second_type:
            return False, "answer_type_mismatch"
        if reason := _token_diff_reason(q_new, q_cached):
            return False, reason
    elif mode == "capitalization":
        if _entities(q_new) != _entities(q_cached):
            return False, "entity_mismatch"
    else:
        raise ValueError(f"Unknown verifier mode: {mode}")

    # --- Tier 2: semantic equivalence (NLI) ---
    if use_nli:
        eq = (verifier or default_verifier()).equivalent(q_new, q_cached)
        if eq is None:
            return False, "nli_unavailable"
        if eq is False:
            return False, "nli_not_equivalent"

    return True, "ok"
