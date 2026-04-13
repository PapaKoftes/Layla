"""Long-running missions API."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.route_helpers import sync_create_and_run_mission

logger = logging.getLogger("layla")
router = APIRouter(tags=["missions"])


@router.post("/mission")
async def create_mission_api(req: Request):
    """Create and start a mission."""
    try:
        body = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        try:
            result = await asyncio.to_thread(sync_create_and_run_mission, body)
            return JSONResponse(result)
        except ValueError as ve:
            msg = str(ve)
            if msg == "goal required":
                return JSONResponse({"error": msg}, status_code=400)
            return JSONResponse({"error": msg}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/mission/{mission_id}")
def get_mission_api(mission_id: str):
    try:
        from layla.memory.db import get_mission

        mission = get_mission(mission_id)
        if not mission:
            return JSONResponse({"error": "mission not found"}, status_code=404)
        return JSONResponse(mission)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/missions")
def list_missions_api(status: str = "", limit: int = 50):
    try:
        from layla.memory.db import get_missions

        status_filter = status if status in ("pending", "running", "completed", "failed") else None
        missions = get_missions(limit=max(1, min(100, limit)), status_filter=status_filter)
        return JSONResponse({"missions": missions})
    except Exception as e:
        return JSONResponse({"error": str(e), "missions": []})
