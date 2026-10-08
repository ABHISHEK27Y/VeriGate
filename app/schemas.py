"""Request/response models."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # Accept either a plain prompt or a list of chat messages.
    prompt: str | None = None
    messages: list[dict] | None = None

    def as_prompt(self) -> str:
        if self.prompt:
            return self.prompt.strip()
        if self.messages:
            # Use the last user message as the cache key text.
            for m in reversed(self.messages):
                if m.get("role") == "user":
                    return str(m.get("content", "")).strip()
            return str(self.messages[-1].get("content", "")).strip()
        return ""


class ChatResponse(BaseModel):
    answer: str
    cache: str = Field(description="HIT | MISS | BYPASS")
    provider: str
    latency_ms: float
    threshold: float | None = None
    similarity: float | None = None
    note: str | None = None
