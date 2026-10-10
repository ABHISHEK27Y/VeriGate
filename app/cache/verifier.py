"""Sub-contribution B: self-verification (reject false hits).

Before serving a candidate cached answer (one that already cleared the similarity
threshold), confirm the two queries are truly equivalent WITHOUT calling the expensive
LLM. Tier-1 symbolic checks catch the failure modes semantic similarity is blind to:

  - numbers/quantities must match     ("5 GB"  vs "50 GB")
  - negation/polarity must match      ("is X safe" vs "is X NOT safe")
  - named entities must match         ("capital of Austria" vs "capital of Australia")

Crucially we do NOT reject on low word overlap: the whole point of semantic matching is
that a valid paraphrase ("reset my password" == "recover my account password") shares
few words. Word-overlap gating would defeat it. Distinguishing subtle paraphrases from
subtle differences beyond entities/numbers/negation is Tier-2's job.

Phase-4 upgrade: Tier-2 = a lightweight NLI cross-encoder for borderline cases, and a
real NER model (spaCy) instead of the capitalization heuristic below.

Policy: conservative on the checks it does make. A miss costs money; a false hit costs
correctness, and we optimize for correctness.
"""

from __future__ import annotations

import functools
import logging
import re
import threading
from collections import OrderedDict

import numpy as np

from ..config import get_settings
from ..embeddings import tokenize

_MAX_NLI_PAIRS = 8192

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


def _numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _negation_flag(text: str) -> bool:
    normalized = text.lower().replace("\u2019", "'").replace("'", "")
    return bool(set(tokenize(normalized)) & _NEGATIONS)


def _entities(text: str) -> set[str]:
    """Capitalization-based proper-noun proxy: capitalized words that are not the first
    token and not common sentence-starters. (Phase-4: replace with spaCy NER.)"""
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
class NliVerifier:
    """Application-owned lazy model with a bounded pair cache."""

    def __init__(self):
        self.model = None
        self.unavailable = False
        self.lock = threading.Lock()
        self.cache: OrderedDict[tuple[str, str], float | None] = OrderedDict()

    def entail_prob(self, premise: str, hypothesis: str) -> float | None:
        key = (premise, hypothesis)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            if self.unavailable:
                return None
            try:
                if self.model is None:
                    from sentence_transformers import (  # noqa: PLC0415 - lazy ML dependency
                        CrossEncoder,  # noqa: PLC0415 - lazy ML dependency
                    )

                    self.model = CrossEncoder(
                        get_settings().nli_model, revision=get_settings().nli_revision or None
                    )
                logits = np.asarray(self.model.predict([(premise, hypothesis)])).reshape(-1)
                labels = self.model.model.config.id2label
                entail = next(
                    (int(i) for i, label in labels.items() if "entail" in label.lower()), None
                )
                if entail is None:
                    raise ValueError("NLI model must identify its entailment label")  # noqa: TRY301 - fail closed
                probs = np.exp(logits - logits.max())
                result = float(probs[entail] / probs.sum())
            except Exception:
                log.exception("NLI unavailable; rejecting semantic reuse")
                self.unavailable = True
                return None
            self.cache[key] = result
            if len(self.cache) > _MAX_NLI_PAIRS:
                self.cache.popitem(last=False)
            return result

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


def verify_equivalent(
    q_new: str, q_cached: str, use_nli: bool = False, verifier: NliVerifier | None = None
) -> tuple[bool, str]:
    """Return (is_equivalent, reason). Tier-1 always; Tier-2 (NLI) when use_nli=True."""
    # --- Tier 1: structural checks ---
    if _numbers(q_new) != _numbers(q_cached):
        return False, "number_mismatch"
    if _negation_flag(q_new) != _negation_flag(q_cached):
        return False, "negation_mismatch"
    if _entities(q_new) != _entities(q_cached):
        return False, "entity_mismatch"

    # --- Tier 2: semantic equivalence (NLI) ---
    if use_nli:
        eq = (verifier or default_verifier()).equivalent(q_new, q_cached)
        if eq is None:
            return False, "nli_unavailable"
        if eq is False:
            return False, "nli_not_equivalent"

    return True, "ok"
