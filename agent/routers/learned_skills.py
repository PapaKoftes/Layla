"""Learned-skills router (BL-238) — skills acquired from successful tasks."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/skills/learned", tags=["skills"])


class AcquireBody(BaseModel):
    state: dict[str, Any]
    name: str = ""
    description: str = ""


class InvokeBody(BaseModel):
    params: dict[str, str] = {}
    confirm: bool = False


@router.get("")
def list_learned():
    from services.skills.skill_acquisition import list_learned_skills
    return {"skills": list_learned_skills()}


@router.post("/acquire")
def acquire(body: AcquireBody):
    from services.skills.skill_acquisition import acquire_from_run
    return acquire_from_run(body.state, name=body.name, description=body.description)


@router.get("/{name}")
def get_learned(name: str):
    from services.skills.skill_acquisition import get_learned_skill
    s = get_learned_skill(name)
    return s or {"ok": False, "error": "skill not found"}


@router.delete("/{name}")
def forget(name: str):
    from services.skills.skill_acquisition import forget_skill
    return forget_skill(name)


@router.post("/{name}/invoke")
def invoke(name: str, body: InvokeBody):
    from services.skills.skill_acquisition import invoke_skill
    return invoke_skill(name, params=body.params, confirm=body.confirm)
