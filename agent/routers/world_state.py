"""World state model router (BL-241)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/world", tags=["world"])


@router.get("")
def world_snapshot():
    """A unified live view over project context, open projects, index, hardware, mode."""
    from services.workspace.world_state import snapshot
    return snapshot()


@router.get("/summary")
def world_summary():
    from services.workspace.world_state import summarize
    return {"summary": summarize()}
