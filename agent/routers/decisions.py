"""Decision memory router (BL-235) — recall why Layla chose what it chose."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/decisions", tags=["decisions"])


class RecordBody(BaseModel):
    goal: str
    chosen: str
    chosen_name: str = ""
    rationale: str = ""
    alternatives: list[Any] = []
    assumptions: list[Any] = []
    context: str = ""
    project: str = ""


@router.get("")
def list_decisions(limit: int = 50, project: str = ""):
    from services.memory.decision_memory import list_decisions as _list
    return {"decisions": _list(limit=limit, project=project)}


@router.get("/search")
def search_decisions(q: str, limit: int = 20):
    from services.memory.decision_memory import search_decisions as _search
    return {"query": q, "decisions": _search(q, limit=limit)}


@router.get("/{decision_id}")
def get_decision(decision_id: int):
    from services.memory.decision_memory import get_decision as _get
    d = _get(decision_id)
    return d or {"ok": False, "error": "decision not found"}


@router.post("")
def record_decision(body: RecordBody):
    from services.memory.decision_memory import record_decision as _rec
    return _rec(
        body.goal, body.chosen, chosen_name=body.chosen_name, rationale=body.rationale,
        alternatives=body.alternatives, assumptions=body.assumptions,
        context=body.context, project=body.project,
    )
