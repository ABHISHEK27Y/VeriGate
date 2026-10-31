"""Development-only fixed-answer provider for isolated HTTP evaluations.

The gateway's retrieval and acceptance code never receives the answer map.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from .base import Provider


class ControlledEvaluationProvider(Provider):
    name = "controlled-eval"
    implicit_completion_is_safe = True

    def __init__(self, path: str) -> None:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not payload:
            raise ValueError("Controlled answer map must be a nonempty object")
        if any(
            not isinstance(q, str) or not isinstance(a, str) or not a for q, a in payload.items()
        ):
            raise ValueError("Controlled answer map has invalid entries")
        self._answers: dict[str, str] = payload

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        try:
            yield self._answers[prompt]
        except KeyError as exc:
            raise ValueError("Question absent from controlled answer map") from exc
