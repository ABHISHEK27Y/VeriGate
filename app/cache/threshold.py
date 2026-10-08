"""Sub-contribution A: adaptive per-query similarity threshold.

Instead of one global cutoff, compute T(q) from query features so that fact-dense /
short queries are matched STRICTLY and long open-ended queries LOOSELY.

Scaffold version: interpretable heuristic. Phase-4 upgrade: learn the weights (or a
logistic-regression accept-classifier) on the benchmark validation split.
"""
from __future__ import annotations

import re

from ..config import settings
from ..embeddings import tokenize

_NUMBER_RE = re.compile(r"\b\d+([.,]\d+)?\b")
# crude "entity" proxy: capitalized words that are not sentence-initial-only
_CAP_RE = re.compile(r"\b[A-Z][a-zA-Z]+\b")

T_MIN = 0.70
T_MAX = 0.98


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def entity_density(query: str) -> float:
    toks = tokenize(query)
    if not toks:
        return 0.0
    caps = len(_CAP_RE.findall(query))
    return caps / len(toks)


def has_number(query: str) -> bool:
    return bool(_NUMBER_RE.search(query))


def shortness(query: str) -> float:
    """Return higher for shorter queries (0..1)."""
    n = len(tokenize(query))
    if n <= 3:
        return 1.0
    if n >= 20:
        return 0.0
    return (20 - n) / 17.0


def adaptive_threshold(query: str, neighbourhood_density: float = 0.0) -> float:
    """Compute T(q). Higher => stricter match required.

    neighbourhood_density in [0,1]: how crowded the vector space is near this query
    (many near-but-distinct neighbours => be stricter).
    """
    base = settings.cache_similarity_base
    t = (
        base
        + 0.10 * entity_density(query)      # w1: proper nouns -> stricter
        + 0.06 * (1.0 if has_number(query) else 0.0)  # w2: numbers -> stricter
        + 0.06 * shortness(query)           # w3: short -> stricter
        + 0.06 * neighbourhood_density      # w4: crowded -> stricter
    )
    return _clip(t, T_MIN, T_MAX)
