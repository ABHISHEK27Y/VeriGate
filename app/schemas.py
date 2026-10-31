"""Request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    content: str = Field(min_length=1, max_length=16000)


class ChatRequest(BaseModel):
    """Stateless single-turn API; reject unsupported history instead of dropping it."""

    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(default=None, max_length=16000)
    messages: list[UserMessage] | None = Field(default=None, min_length=1, max_length=1)
    cache_bypass: bool = False
    cache_scope: Literal["private", "workspace"] = "private"
    workspace: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def one_input(self):
        if self.prompt is not None and self.messages is not None:
            raise ValueError("Supply prompt or one user message, not both")
        if self.workspace and self.cache_scope != "workspace":
            raise ValueError("Workspace requires workspace cache scope")
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
    intended_provider: str | None = None
    fallback_used: bool = False
    latency_ms: float
    threshold: float | None = None
    similarity: float | None = None
    note: str | None = None
    selected_cached_query: str | None = None
    nli_score: float | None = None
    verifier_invoked: bool | None = None
    stage_latency_ms: dict[str, float] | None = None
    organization_id: str | None = None
    subject_id: str | None = None
    cache_scope: str | None = None
    provider_profile: str | None = None
    candidate_count: int | None = None
    selected_rank: int | None = None
    storage_outcome: str | None = None
