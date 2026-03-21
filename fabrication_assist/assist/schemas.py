"""Strict Pydantic schemas for intent, variant configs, kernel results, and history rows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_USER_TEXT_CHARS = 200_000


class IntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw: str = Field(..., max_length=MAX_USER_TEXT_CHARS)
    goal: str = Field(..., max_length=256)
    strategies: list[str] = Field(default_factory=list)

    @field_validator("strategies")
    @classmethod
    def _cap_strategies(cls, v: list[str]) -> list[str]:
        if len(v) > 64:
            raise ValueError("too many strategy tags")
        return v


class VariantConfigModel(BaseModel):
    """Aligned with propose_variants(); unknown keys ignored for forward compatibility."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., max_length=256)
    label: str = Field(..., max_length=512)
    goal: str | None = Field(None, max_length=256)
    strategy: str | None = Field(None, max_length=256)
    material: str | None = Field(None, max_length=256)
    connection: str | None = Field(None, max_length=256)
    tolerance_class: str | None = Field(None, max_length=64)
    machining_priority: str | None = Field(None, max_length=256)


class ProductResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(..., max_length=256)
    label: str = Field(..., max_length=512)
    score: float
    metrics: dict[str, Any] = Field(default_factory=dict)
    feasible: bool = True
    notes: str = Field(default="", max_length=16_384)

    @field_validator("metrics", mode="before")
    @classmethod
    def _metrics_as_dict(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        raise TypeError("metrics must be a dict")


class HistoryEntryModel(BaseModel):
    """Metadata-only row appended to session history."""

    model_config = ConfigDict(extra="forbid")

    user: str = Field(..., max_length=MAX_USER_TEXT_CHARS)
    intent: dict[str, Any]
    variant_ids: list[str | None]
    result_scores: list[Any]
