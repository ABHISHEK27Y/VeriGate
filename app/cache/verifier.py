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

import numpy as np

from ..config import settings
from ..embeddings import tokenize

log = logging.getLogger("verigate.verifier")

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_NEGATIONS = {"not", "no", "never", "without", "cannot", "cant", "dont", "doesnt", "isnt"}
# Common words that are capitalized as sentence-starters, not because they're entities.
_NON_ENTITY_CAPS = {
    "what", "how", "when", "where", "why", "who", "which", "is", "are", "do", "does",
    "can", "could", "would", "should", "tell", "give", "list", "explain", "the", "a",
    "an", "please", "i", "my", "me",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z]+")


def _numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _negation_flag(text: str) -> bool:
    return bool(set(tokenize(text)) & _NEGATIONS)


def _entities(text: str) -> set[str]:
    """Capitalization-based proper-noun proxy: capitalized words that are not the first
    token and not common sentence-starters. (Phase-4: replace with spaCy NER.)"""
    words = _WORD_RE.findall(text)
    ents = set()
    for i, w in enumerate(words):
        if w[0].isupper() and i > 0 and w.lower() not in _NON_ENTITY_CAPS:
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
_nli_model = None
_nli_unavailable = False


def _load_nli():
    global _nli_model, _nli_unavailable
    if _nli_model is not None or _nli_unavailable:
        return
    try:
        from sentence_transformers import CrossEncoder

        log.info("Loading NLI model %s ...", settings.nli_model)
        _nli_model = CrossEncoder(settings.nli_model)
    except Exception as e:  # noqa: BLE001 - any failure -> disable Tier-2 (fail-open)
        log.warning("NLI model unavailable (%s); Tier-2 disabled.", e)
        _nli_unavailable = True


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


@functools.lru_cache(maxsize=8192)
def _entail_prob(premise: str, hypothesis: str) -> float | None:
    """P(premise entails hypothesis). None if NLI is unavailable."""
    _load_nli()
    if _nli_model is None:
        return None
    # cross-encoder/nli-* label order is [contradiction, entailment, neutral]
    logits = np.array(_nli_model.predict([(premise, hypothesis)])).reshape(-1)
    return float(_softmax(logits)[1])


def nli_equivalent(q1: str, q2: str) -> bool | None:
    """True/False if NLI is available (bidirectional entailment); None if unavailable."""
    e1 = _entail_prob(q1, q2)
    e2 = _entail_prob(q2, q1)
    if e1 is None or e2 is None:
        return None
    thr = settings.nli_threshold
    return e1 >= thr and e2 >= thr


def verify_equivalent(q_new: str, q_cached: str, use_nli: bool = False) -> tuple[bool, str]:
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
        eq = nli_equivalent(q_new, q_cached)
        if eq is False:  # None => unavailable => fail-open (keep Tier-1 verdict)
            return False, "nli_not_equivalent"

    return True, "ok"
