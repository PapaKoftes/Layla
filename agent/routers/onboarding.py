"""
onboarding.py — Onboarding interview API endpoints.

Endpoints:
  GET  /onboarding/status     — Check if onboarding is needed + current state
  GET  /onboarding/stage      — Get current stage info (opener, followups)
  POST /onboarding/start      — Start or resume the interview
  POST /onboarding/response   — Submit user's response for current stage
  POST /onboarding/advance    — Move to the next stage
  POST /onboarding/complete   — Mark interview as complete
  POST /onboarding/skip       — Skip the interview entirely

Phase 4C of the distributed infrastructure plan.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("layla.onboarding")

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ── Request / Response models ────────────────────────────────────────────

class StageResponse(BaseModel):
    stage: str
    data: dict = Field(default_factory=dict)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/status")
async def onboarding_status():
    """Check onboarding state — is it needed, in progress, or complete?"""
    try:
        from services.user.onboarding_interview import get_onboarding
        ob = get_onboarding()
        needs = ob.needs_onboarding()
        state = ob.get_state()

        return {
            "needs_onboarding": needs,
            "in_progress": state is not None and not state.is_complete,
            "state": state.to_dict() if state else None,
        }
    except Exception as e:
        logger.warning("Onboarding status check failed: %s", e)
        return {
            "needs_onboarding": True,
            "in_progress": False,
            "state": None,
            "error": str(e),
        }


@router.get("/stage")
async def onboarding_stage():
    """Get the current interview stage info."""
    try:
        from services.user.onboarding_interview import get_onboarding
        ob = get_onboarding()
        info = ob.get_current_stage_info()
        return {"ok": True, **info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def onboarding_start():
    """Start or resume the onboarding interview."""
    try:
        from services.user.onboarding_interview import get_onboarding
        ob = get_onboarding()
        state = ob.start()
        stage_info = ob.get_current_stage_info()
        return {
            "ok": True,
            "state": state.to_dict(),
            "stage_info": stage_info,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/response")
async def onboarding_response(body: StageResponse):
    """Submit the user's response for a stage."""
    try:
        from services.user.onboarding_interview import get_onboarding
        ob = get_onboarding()
        result = ob.submit_response(body.stage, body.data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/advance")
async def onboarding_advance():
    """Advance to the next interview stage."""
    try:
        from services.user.onboarding_interview import get_onboarding
        ob = get_onboarding()
        result = ob.advance()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete")
async def onboarding_complete():
    """Mark the interview as complete."""
    try:
        from services.user.onboarding_interview import get_onboarding
        ob = get_onboarding()
        result = ob.complete()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skip")
async def onboarding_skip():
    """Skip the onboarding interview."""
    try:
        from services.user.onboarding_interview import get_onboarding
        ob = get_onboarding()
        result = ob.skip()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
