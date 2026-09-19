"""Sub-contribution C: staleness / volatility detection.

Time-sensitive queries must never be cached, because their correct answer changes.
Scaffold version: keyword rules. Phase-4 upgrade: add a trained classifier for recall.
"""
from __future__ import annotations

import re

_VOLATILE_KEYWORDS = {
    "today", "now", "current", "currently", "latest", "live", "right now",
    "this week", "this month", "this year", "tonight", "tomorrow", "yesterday",
    "price", "weather", "temperature", "score", "news", "stock", "exchange rate",
    "trending", "recent", "up to date", "as of",
}

_VOLATILE_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _VOLATILE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_volatile(query: str) -> bool:
    """True if the query's answer is likely time-sensitive (skip caching)."""
    return bool(_VOLATILE_RE.search(query))
