"""Explainable reasoning router (BL-237)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/explain", tags=["explain"])


class ExplainBody(BaseModel):
    steps: list[dict[str, Any]] = []
    goal: str = ""
    answer: str = ""


@router.post("")
def explain(body: ExplainBody):
    """Build a concise 'why' summary from a run trace (steps + goal + answer)."""
    from services.agent.explain import build_explanation
    return build_explanation(body.steps, goal=body.goal, answer=body.answer)
