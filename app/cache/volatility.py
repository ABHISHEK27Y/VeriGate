"""Sub-contribution C: staleness / volatility detection.

Time-sensitive queries must never be cached, because their correct answer changes.
Scaffold version: keyword rules. Phase-4 upgrade: add a trained classifier for recall.
"""

from __future__ import annotations

import re

_VOLATILE_KEYWORDS = {
    "today",
    "now",
    "current",
    "currently",
    "latest",
    "live",
    "right now",
    "this week",
    "this month",
    "this year",
    "tonight",
    "tomorrow",
    "yesterday",
    "price",
    "prices",
    "weather",
    "temperature",
    "score",
    "news",
    "stock",
    "stocks",
    "what time",
    "time in",
    "the time",
    "exchange rate",
    "trending",
    "recent",
    "up to date",
    "as of",
}

_VOLATILE_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _VOLATILE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_EXPLICIT_TIME_RE = re.compile(
    r"\b(?:today|now|currently|latest|live|right now|this week|this month|"
    r"this year|tonight|tomorrow|yesterday|recent|up to date|as of)\b",
    re.IGNORECASE,
)
_CONCEPT_REQUEST_RE = re.compile(
    r"^\s*(?:define\b|what does .{1,100}\bmean\b|what is an?\b|"
    r"what is the difference between\b)",
    re.IGNORECASE,
)
_IN_PRINCIPLE_RE = re.compile(r"\bin principle\b", re.IGNORECASE)


def is_volatile(query: str) -> bool:
    """True if the query's answer is likely time-sensitive (skip caching)."""
    if not _VOLATILE_RE.search(query):
        return False
    if _EXPLICIT_TIME_RE.search(query):
        return True
    # A clearly definitional request asks for a concept, not its current value.
    # Unclear uses of price, score or current still bypass.
    return not (_CONCEPT_REQUEST_RE.search(query) or _IN_PRINCIPLE_RE.search(query))
