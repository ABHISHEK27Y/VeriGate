"""Sub-contribution C: staleness / volatility detection.

Time-sensitive queries must never be cached, because their correct answer changes.

This is a conservative, context-aware heuristic, not a trained classifier. It
distinguishes a request for a *changing value* (bypass) from a *stable procedure
or concept* that merely mentions a value or time word (cache). Two word classes:

  * absolute-time references (today, now, tomorrow, as of ...) make an answer
    time-bound unless the query is a pure concept request; and
  * value / recency words (price, score, current, latest, live ...) make an
    answer time-bound only when the query asks for the value itself — not when
    they name a construct ("price field", "current user") or appear in a
    "how do I ..." procedure or a "what is a ..." concept request.

It still bypasses genuine volatile queries that lack an explicit today/now
("the price of gold", "who is the current CEO"). Known limits: polysemous nouns
(a musical "score", an electrical "current") can still be misclassified. A
trained classifier remains the Phase-4 upgrade for recall.
"""

from __future__ import annotations

import re

# Absolute wall-clock references: the answer changes with time regardless of the
# surrounding construct. Only a pure concept request (define/explain) rescues these.
_ABSOLUTE_TIME_RE = re.compile(
    r"\b(?:today|now|right now|tonight|tomorrow|yesterday|this week|this month|"
    r"this year|these days|at the moment|this morning|this afternoon|this evening)\b"
    r"|\bas of\b|\bwhat time\b",
    re.IGNORECASE,
)

# Value nouns: volatile when the query asks for the value ("price of gold"),
# stable when used as a compound modifier ("price field").
_VALUE_NOUN = (
    r"price|prices|score|scores|temperature|temperatures|weather|stock|stocks|"
    r"news|exchange rate|exchange rates"
)
# Recency / state words: volatile when asking for the current value, stable in a
# procedure or concept, or when naming a construct.
_RECENCY = r"current|currently|latest|live|recent|recently|up to date|up-to-date|trending"

_CHANGING_RE = re.compile(rf"\b(?:{_VALUE_NOUN}|{_RECENCY})\b", re.IGNORECASE)
_RECENCY_RE = re.compile(rf"\b(?:{_RECENCY})\b", re.IGNORECASE)

# "How do I ...", "steps to ...": a procedure whose answer is stable even when it
# mentions a value/recency word. Deliberately excludes "how much/how many", which
# can ask for a changing quantity.
_PROCEDURE_RE = re.compile(
    r"^\s*(?:how\s+(?:to|do|does|did|can|could|should|would|will|are|is|was|were)\b"
    r"|steps?\s+to\b|in order to\b|guide\s+to\b)",
    re.IGNORECASE,
)

# Concept / definition requests: the concept is stable even if the phrasing
# contains a time or value word ("explain the now() function", "what is a score").
_CONCEPT_RE = re.compile(
    r"\bdefine\b|\bexplain\b|\bwhat\s+is\s+an?\b|"
    r"\bwhat\s+does\b.{1,100}\bmean\b|\bdifference between\b|"
    r"\bin principle\b|\bmeaning of\b",
    re.IGNORECASE,
)

# A value noun used as a compound modifier names a concept, not a live value
# ("price mechanism", "temperature sensor"). Excluded when followed by "of"
# (a value request) or by a time word.
_VALUE_NOUN_COMPOUND_RE = re.compile(
    rf"\b(?:{_VALUE_NOUN})\s+"
    r"(?!of\b|is\b|are\b|was\b|were\b|now\b|today\b|for\b|in\b|on\b|at\b)[a-z]+",
    re.IGNORECASE,
)

# A time word naming a programming/SQL construct is not a temporal reference:
# NOW(), current_timestamp, "the now() function", current_date.
_TIME_CONSTRUCT_RE = re.compile(
    r"\bnow\s*\(|\bnow\s+(?:function|method|call|clause|keyword|timestamp)\b"
    r"|\bcurrent_timestamp\b|\bcurrent_date\b|\bgetdate\b|\bsysdate\b",
    re.IGNORECASE,
)


def is_volatile(query: str) -> bool:
    """True if the query's answer is likely time-sensitive (skip caching)."""
    has_absolute = bool(_ABSOLUTE_TIME_RE.search(query)) and not _TIME_CONSTRUCT_RE.search(query)
    if not (has_absolute or _CHANGING_RE.search(query)):
        return False
    # An absolute wall-clock reference (today/now/tomorrow) makes the answer
    # time-bound; a concept request does not rescue it. Time words that name a
    # construct (SQL NOW()) were already excluded above.
    if has_absolute:
        return True
    # No absolute time, but a value/recency word is present.
    # A definition/concept request asks what something means, not its current value.
    if _CONCEPT_RE.search(query):
        return False
    # A "how do I ..." procedure's answer is stable over value/recency words.
    if _PROCEDURE_RE.search(query):
        return False
    # A recency word ("current", "latest", "live") asks for the present value.
    if _RECENCY_RE.search(query):
        return True
    # Only a value noun remains: stable when used as a compound modifier
    # ("price field"), volatile when it is the value being asked for.
    return _VALUE_NOUN_COMPOUND_RE.search(query) is None
