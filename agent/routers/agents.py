"""Tiny-agent / worker spawn: threaded autonomous_run at agent-tier priority by default.

Poll status via GET /agent/tasks/{task_id} (same store as /agent/background)."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from routers.agent import enqueue_threaded_autonomous
from services.resource_manager import PRIORITY_AGENT
from shared_state import get_touch_activity

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/spawn")
def spawn_tiny_agent(req: dict):
    """Queue an autonomous run in a daemon thread (kind=tiny_agent). Body matches /agent/background."""
    get_touch_activity()()
    out = enqueue_threaded_autonomous(req or {}, default_priority=PRIORITY_AGENT, kind="tiny_agent")
    if not out.get("ok"):
        return JSONResponse(out, status_code=400)
    tid = out["task_id"]
    return JSONResponse(
        {
            "ok": True,
            "agent_id": tid,
            "task_id": tid,
            "conversation_id": out.get("conversation_id"),
            "status": out.get("status", "queued"),
            "kind": "tiny_agent",
            "schedule_priority": out.get("schedule_priority"),
            "poll_path": f"/agent/tasks/{tid}",
            "allow_write": out.get("allow_write"),
            "allow_run": out.get("allow_run"),
            "workspace_root": out.get("workspace_root"),
            "worker_mode": out.get("worker_mode", "thread"),
            "isolation": {
                "conversation_scoped_history": True,
                "note": "Each task gets its own conversation_id unless you pass one explicitly; history is keyed by that id.",
            },
        }
    )
