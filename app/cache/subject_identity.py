"""Conservative identity check for explicitly named works in cache questions.

This is a syntax guard, not an entity linker. Unknown forms pass to the existing
policy; different extracted subjects cannot be made equivalent by NLI alone.
"""

from __future__ import annotations

import re

from ..embeddings import tokenize

_KIND = {
    "song": "song",
    "album": "album",
    "novel": "book",
    "book": "book",
    "film": "film",
    "movie": "film",
    "poem": "poem",
    "painting": "painting",
    "play": "play",
}
_NAMED_WORK = re.compile(
    r"\b(?:the|a|an)\s+"
    r"(?P<kind>song|album|novel|book|film|movie|poem|painting|play)\s+"
    r"(?P<title>.+?)"
    r"(?=,\s*(?:who|what|which|when|where|how|name|identify)\b|[?.!]\s*$|$)",
    re.IGNORECASE,
)


def named_work(question: str) -> tuple[str, tuple[str, ...]] | None:
    """Return a typed title only when a work is explicitly named."""
    matches = list(_NAMED_WORK.finditer(question))
    if len(matches) != 1:
        return None
    match = matches[0]
    title = tokenize(match.group("title"))
    # A leading article is a common title variant; retain every other token.
    if len(title) > 1 and title[0] == "the":
        title = title[1:]
    return (_KIND[match.group("kind").casefold()], tuple(title)) if title else None


def conflicting_named_work(incoming: str, stored: str) -> bool:
    """Different explicit titles or media types cannot authorize answer reuse."""
    left, right = named_work(incoming), named_work(stored)
    return left is not None and right is not None and left != right
