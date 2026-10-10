"""Request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class UserMessage(BaseModel):
    role: Literal["user"]
    content: str = Field(min_length=1, max_length=16000)


class ChatRequest(BaseModel):
    """Stateless single-turn API; reject unsupported history instead of dropping it."""

    prompt: str | None = Field(default=None, max_length=16000)
    messages: list[UserMessage] | None = Field(default=None, min_length=1, max_length=1)

    @model_validator(mode="after")
    def one_input(self):
        if self.prompt is not None and self.messages is not None:
            raise ValueError("Supply prompt or one user message, not both")
        return self

    def as_prompt(self) -> str:
        if self.prompt is not None:
            return self.prompt.strip()
        if self.messages:
            return self.messages[0].content.strip()
        return ""


class ChatResponse(BaseModel):
    answer: str
    cache: str = Field(description="HIT | MISS | BYPASS")
    provider: str
    latency_ms: float
    threshold: float | None = None
    similarity: float | None = None
    note: str | None = None
