"""Query-complexity estimation for cost-aware routing (the model cascade).

Idea: not every query needs an expensive model. A cheap/small model answers simple factual
queries fine; only *hard* queries (reasoning, multi-step, code, comparison) need the strong
model. This module scores a query 0..1 so the router can send easy queries to the cheap model
and escalate only the hard ones — cutting cost while preserving quality.

Scaffold: an interpretable heuristic. Phase-2 upgrade: train a small classifier on labelled
easy/hard queries (see evaluation/cascade.py for the benchmark).
"""
from __future__ import annotations

import re

_HARD_WORDS = {
    "why", "explain", "compare", "comparison", "difference", "differences", "versus", "vs",
    "analyze", "analyse", "prove", "derive", "evaluate", "design", "optimize", "optimise",
    "reason", "reasoning", "implications", "tradeoff", "tradeoffs", "trade-off", "architecture",
    "debug", "refactor", "algorithm", "complexity", "summarize", "summarise", "pros and cons",
    "step by step", "how would", "how do i implement", "walk me through", "critique",
}
_CODE = re.compile(r"```|def |class |function |select \*|import |{.*}|=>|public |void ")
_MATH = re.compile(r"\b(integral|derivative|matrix|probability|theorem|equation|gradient)\b")


def complexity_score(query: str) -> float:
    """Return a 0..1 estimate of how 'hard' a query is (higher = needs the strong model)."""
    q = query.lower().strip()
    toks = q.split()
    n = len(toks)
    score = 0.0

    # length: longer prompts tend to need more capable models
    score += min(1.0, n / 45) * 0.35
    # reasoning / analytical intent
    if any(w in q for w in _HARD_WORDS):
        score += 0.35
    # code or math content
    if _CODE.search(query) or _MATH.search(q):
        score += 0.30
    # multiple sub-questions / compound requests
    if q.count("?") > 1 or " and " in q or ";" in q:
        score += 0.12
    # explicit comparison
    if any(w in q for w in ("compare", "versus", " vs ", "difference", "tradeoff", "trade-off")):
        score += 0.15

    return min(1.0, score)


def is_hard(query: str, threshold: float = 0.5) -> bool:
    return complexity_score(query) >= threshold
