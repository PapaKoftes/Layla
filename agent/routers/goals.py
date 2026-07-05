"""Goals router (BL-240) — dashboard + proactive suggestions over the goals store."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/goals", tags=["goals"])


class GoalBody(BaseModel):
    title: str
    description: str = ""
    project_id: str = ""


class ProgressBody(BaseModel):
    note: str = ""
    progress_pct: float = 0.0


class StatusBody(BaseModel):
    status: str  # active | done | paused | dropped


@router.get("")
def dashboard(project_id: str = ""):
    from services.planning.goal_tracker import goal_dashboard
    return goal_dashboard(project_id)


@router.get("/suggestions")
def suggestions(project_id: str = ""):
    from services.planning.goal_tracker import proactive_suggestions
    return {"suggestions": proactive_suggestions(project_id)}


@router.post("")
def create(body: GoalBody):
    from layla.memory.user_profile import add_goal
    return {"ok": True, "goal_id": add_goal(body.title, body.description, body.project_id)}


@router.post("/{goal_id}/progress")
def progress(goal_id: str, body: ProgressBody):
    from layla.memory.user_profile import add_goal_progress
    add_goal_progress(goal_id, body.note, body.progress_pct)
    return {"ok": True}


@router.post("/{goal_id}/status")
def set_status(goal_id: str, body: StatusBody):
    from layla.memory.user_profile import set_goal_status
    set_goal_status(goal_id, body.status)
    return {"ok": True}
