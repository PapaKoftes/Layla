"""Pydantic request models for API endpoints.

Replaces raw ``dict`` request bodies with typed, validated models.
FastAPI returns 422 automatically when validation fails.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentRequest(BaseModel):
    """POST /agent — main agent chat endpoint."""

    message: str = Field("", max_length=100_000, description="User message / goal")
    context: str = Field("", max_length=100_000, description="Additional context")
    workspace_root: str = Field("", max_length=2000)
    image_url: str = Field("", max_length=4000)
    image_base64: str = Field("", max_length=10_000_000)
    allow_write: bool = False
    allow_run: bool = False
    aspect_id: str = Field("", max_length=64)
    persona_focus: str = Field("", alias="persona_focus", max_length=64)
    personaFocus: str | None = Field(None, max_length=64, exclude=True)
    show_thinking: bool = False
    plan_mode: bool = False
    understand_mode: bool = False
    stream: bool = False
    model_override: str = Field("", max_length=200)
    reasoning_effort: str | None = None
    conversation_id: str = Field("", max_length=200)
    plan_id: str = Field("", max_length=200)
    engineering_pipeline_mode: str | None = None
    cognition_workspace_roots: list[str] | None = None
    research_mode: bool = False
    project_id: str = Field("", max_length=200)
    clarification_reply: str = Field("", max_length=100_000)
    understand_index_semantic: bool = False

    class Config:
        populate_by_name = True

    def effective_persona_focus(self) -> str:
        """Return the persona_focus, falling back to the camelCase alias."""
        return (self.persona_focus or self.personaFocus or "").strip()


class DebateRequest(BaseModel):
    """POST /debate — multi-aspect deliberation endpoint."""

    goal: str = Field(..., min_length=1, max_length=100_000, description="Deliberation goal")
    mode: str = Field("auto", max_length=20, description="Deliberation mode")
    aspects: list[str] | None = None
    state: dict[str, Any] = Field(default_factory=dict)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        allowed = {"auto", "solo", "debate", "council", "tribunal"}
        val = v.strip().lower()
        if val not in allowed:
            raise ValueError(f"mode must be one of {allowed}")
        return val


class LearnRequest(BaseModel):
    """POST /learn/ — save a new learning."""

    content: str = Field(..., min_length=1, max_length=100_000, description="Learning content")
    type: str = Field("fact", max_length=50)
    tags: str = Field("", max_length=500)
    aspect_id: str = Field("", max_length=64)


class ScheduleRequest(BaseModel):
    """POST /schedule — schedule a tool for background execution."""

    tool_name: str = Field(..., min_length=1, max_length=200, description="Tool to schedule")
    args: dict[str, Any] = Field(default_factory=dict)
    delay_seconds: float = Field(0, ge=0, le=86400)
    cron_expr: str = Field("", max_length=100)


class SteerRequest(BaseModel):
    """POST /agent/steer — redirect an in-flight agent run."""

    hint: str = Field("", max_length=10_000)
    steer: str = Field("", max_length=10_000)
    message: str = Field("", max_length=10_000)
    conversation_id: str = Field("", max_length=200)

    def effective_hint(self) -> str:
        return (self.hint or self.steer or self.message or "").strip()
