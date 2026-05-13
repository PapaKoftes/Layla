"""Long-running missions API.

Provides full mission lifecycle management:
  POST /mission          — Create and start a mission
  GET  /mission/{id}     — Get mission details
  GET  /missions         — List missions (optional status filter)
  POST /mission/{id}/pause   — Pause a running mission
  POST /mission/{id}/resume  — Resume a paused mission
  POST /mission/{id}/cancel  — Cancel/abort a mission
  GET  /missions/board       — Kanban-style board (backlog/running/paused/done)
  GET  /missions/horizon     — List long-horizon plan checkpoints
"""
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

        status_filter = status if status in ("pending", "running", "completed", "failed", "paused") else None
        missions = get_missions(limit=max(1, min(100, limit)), status_filter=status_filter)
        return JSONResponse({"missions": missions})
    except Exception as e:
        return JSONResponse({"error": str(e), "missions": []})


@router.post("/mission/{mission_id}/pause")
def pause_mission_api(mission_id: str):
    """Pause a running mission. It can be resumed later."""
    try:
        from layla.memory.missions_db import get_mission, update_mission_progress

        mission = get_mission(mission_id)
        if not mission:
            return JSONResponse({"error": "mission not found"}, status_code=404)
        if mission.get("status") != "running":
            return JSONResponse({"error": f"cannot pause mission in status '{mission.get('status')}'"}, status_code=400)
        update_mission_progress(mission_id, status="paused")
        return JSONResponse({"ok": True, "mission_id": mission_id, "status": "paused"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/mission/{mission_id}/resume")
def resume_mission_api(mission_id: str):
    """Resume a paused mission."""
    try:
        from layla.memory.missions_db import get_mission, update_mission_progress

        mission = get_mission(mission_id)
        if not mission:
            return JSONResponse({"error": "mission not found"}, status_code=404)
        if mission.get("status") not in ("paused", "pending"):
            return JSONResponse({"error": f"cannot resume mission in status '{mission.get('status')}'"}, status_code=400)
        update_mission_progress(mission_id, status="running")
        return JSONResponse({"ok": True, "mission_id": mission_id, "status": "running"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/mission/{mission_id}/cancel")
def cancel_mission_api(mission_id: str):
    """Cancel/abort a mission."""
    try:
        from layla.memory.missions_db import get_mission, update_mission_progress

        mission = get_mission(mission_id)
        if not mission:
            return JSONResponse({"error": "mission not found"}, status_code=404)
        if mission.get("status") in ("completed", "failed"):
            return JSONResponse({"error": f"mission already in terminal state '{mission.get('status')}'"}, status_code=400)
        update_mission_progress(mission_id, status="failed")
        return JSONResponse({"ok": True, "mission_id": mission_id, "status": "cancelled"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/missions/board")
def mission_board_api():
    """
    Kanban-style mission board.

    Returns missions grouped by column: backlog, running, paused, done.
    """
    try:
        from layla.memory.db import get_missions

        all_missions = get_missions(limit=100)
        board = {
            "backlog": [],
            "running": [],
            "paused": [],
            "done": [],
        }
        for m in all_missions:
            status = m.get("status", "pending")
            if status == "pending":
                board["backlog"].append(m)
            elif status == "running":
                board["running"].append(m)
            elif status == "paused":
                board["paused"].append(m)
            elif status in ("completed", "failed"):
                board["done"].append(m)
            else:
                board["backlog"].append(m)
        return JSONResponse({
            "board": board,
            "counts": {k: len(v) for k, v in board.items()},
        })
    except Exception as e:
        return JSONResponse({"error": str(e), "board": {}, "counts": {}})


@router.get("/missions/horizon")
def list_horizon_plans_api():
    """List all long-horizon plan checkpoints."""
    try:
        from services.long_horizon_planner import list_checkpoints
        return JSONResponse({"plans": list_checkpoints()})
    except Exception as e:
        return JSONResponse({"error": str(e), "plans": []})
