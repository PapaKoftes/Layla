"""Background tasks, resume, and plan execution routes. Mounted under main agent router."""
import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.agent_task_runner import (
    _TASKS,
    _TASKS_LOCK,
    _cancel_background_task_impl,
    _parse_stored_progress_events,
    _task_public,
    enqueue_threaded_autonomous,
)
from services.resource_manager import PRIORITY_BACKGROUND
from shared_state import get_touch_activity

logger = logging.getLogger("layla")
router = APIRouter(tags=["agent"])


@router.post("/resume")
async def resume_paused(req: dict):
    """Resume a paused-high-load run from its checkpoint. Pass the checkpoint from the paused response."""
    checkpoint = (req or {}).get("checkpoint") or {}
    if not checkpoint:
        return JSONResponse({"ok": False, "error": "checkpoint required"}, status_code=400)
    goal = checkpoint.get("goal") or checkpoint.get("original_goal") or ""
    if not goal:
        return JSONResponse({"ok": False, "error": "checkpoint missing goal"}, status_code=400)
    workspace_root = (req or {}).get("workspace_root", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    aspect_id = (req or {}).get("aspect_id", "") or ""
    from agent_loop import autonomous_run
    result = await asyncio.to_thread(
        autonomous_run,
        goal,
        context=f"[Resuming from checkpoint — {len(checkpoint.get('steps', []))} steps already done]",
        workspace_root=workspace_root,
        allow_write=allow_write,
        allow_run=allow_run,
        conversation_history=[],
        aspect_id=aspect_id or "morrigan",
        conversation_id=str((req or {}).get("conversation_id") or "").strip(),
    )
    return JSONResponse({
        "ok": True,
        "status": result.get("status"),
        "response": (result.get("steps") or [{}])[-1].get("result", "") if result.get("steps") else "",
        "state": result,
    })


@router.post("/agent/persistent_tasks/{task_id}/resume")
async def resume_persistent_coordinator_task(task_id: str, request: Request):
    """Re-enter autonomous_run via coordinator.run using SQLite tasks.execution_state_json."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    import agent_loop as _al
    from services.coordinator import run as coordinator_run

    result = await asyncio.to_thread(
        coordinator_run,
        _al.autonomous_run,
        str(body.get("goal") or "").strip(),
        context=str(body.get("context") or ""),
        workspace_root=str(body.get("workspace_root") or ""),
        allow_write=body.get("allow_write") is True,
        allow_run=body.get("allow_run") is True,
        conversation_id=str(body.get("conversation_id") or "").strip(),
        aspect_id=str(body.get("aspect_id") or "").strip() or "morrigan",
        show_thinking=body.get("show_thinking") is True,
        resume_task_id=(task_id or "").strip(),
    )
    return JSONResponse({"ok": True, "result": result})


@router.post("/execute_plan")
async def execute_plan_route(req: dict):
    """Execute a pre-generated plan (from plan_mode). Steps run sequentially via autonomous_run."""
    plan_steps = (req or {}).get("plan") or []
    goal = (req or {}).get("goal", "") or ""
    workspace_root = (req or {}).get("workspace_root", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    aspect_id = (req or {}).get("aspect_id", "") or ""
    try:
        dm = int((req or {}).get("default_max_retries") or (req or {}).get("step_max_retries") or 1)
    except (TypeError, ValueError):
        dm = 1
    dm = max(0, min(3, dm))
    if not plan_steps or not goal:
        return JSONResponse({"ok": False, "error": "plan and goal are required"}, status_code=400)
    try:
        from agent_loop import autonomous_run
        from services.planner import execute_plan as _exec_plan
        results = await asyncio.to_thread(
            _exec_plan,
            plan_steps,
            autonomous_run,
            "",  # goal_prefix
            0,   # plan_depth
            step_governance=True,
            default_max_retries=dm,
            workspace_root=workspace_root,
            allow_write=allow_write,
            allow_run=allow_run,
            aspect_id=aspect_id or "morrigan",
            conversation_id=str((req or {}).get("conversation_id") or "").strip(),
            plan_approved=True,
            active_plan_id=str((req or {}).get("plan_id") or "").strip(),
        )
        all_ok = bool(results.get("all_steps_ok")) if isinstance(results, dict) else False
        return JSONResponse({
            "ok": True,
            "status": "plan_executed",
            "results": results,
            "goal": goal,
            "all_steps_ok": all_ok,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/agent/background")
def start_background(req: dict):
    get_touch_activity()()
    out = enqueue_threaded_autonomous(req or {}, default_priority=PRIORITY_BACKGROUND, kind="background")
    if not out.get("ok"):
        return JSONResponse(out, status_code=400)
    return JSONResponse(
        {
            "ok": True,
            "task_id": out["task_id"],
            "conversation_id": out["conversation_id"],
            "status": out["status"],
            "allow_write": out.get("allow_write"),
            "allow_run": out.get("allow_run"),
            "workspace_root": out.get("workspace_root"),
            "worker_mode": out.get("worker_mode", "thread"),
        }
    )


@router.get("/agent/tasks")
def list_background_tasks():
    with _TASKS_LOCK:
        items = list(_TASKS.values())
    # Merge persisted rows so completed tasks survive restarts.
    try:
        from layla.memory.db import list_background_tasks as _list_background_tasks_db

        db_items = _list_background_tasks_db(limit=200)
        merged: dict[str, dict] = {}
        for row in db_items:
            rid = row.get("id", "")
            if not rid:
                continue
            merged[rid] = {
                "task_id": rid,
                "conversation_id": row.get("conversation_id", ""),
                "goal": row.get("goal", ""),
                "aspect_id": row.get("aspect_id", ""),
                "status": row.get("status", "queued"),
                "priority": row.get("priority", PRIORITY_BACKGROUND),
                "kind": row.get("kind", "") or "background",
                "created_at": row.get("created_at", ""),
                "started_at": row.get("started_at", ""),
                "finished_at": row.get("finished_at", ""),
                "result": row.get("result", ""),
                "error": row.get("error", ""),
                "progress_events": _parse_stored_progress_events(row.get("progress_json")),
            }
        for item in items:
            tid = item.get("task_id", "")
            if tid:
                merged[tid] = item
        items = list(merged.values())
    except Exception:
        pass
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items = [_task_public(x) if isinstance(x, dict) else x for x in items]
    return JSONResponse({"ok": True, "tasks": items})


@router.get("/agent/tasks/{task_id}")
def get_background_task(task_id: str):
    with _TASKS_LOCK:
        item = _TASKS.get(task_id)
    if not item:
        try:
            from layla.memory.db import get_background_task as _get_background_task_db

            row = _get_background_task_db(task_id)
            if row:
                item = {
                    "task_id": row.get("id", task_id),
                    "conversation_id": row.get("conversation_id", ""),
                    "goal": row.get("goal", ""),
                    "aspect_id": row.get("aspect_id", ""),
                    "status": row.get("status", "queued"),
                    "priority": row.get("priority", PRIORITY_BACKGROUND),
                    "kind": row.get("kind", "") or "background",
                    "created_at": row.get("created_at", ""),
                    "started_at": row.get("started_at", ""),
                    "finished_at": row.get("finished_at", ""),
                    "result": row.get("result", ""),
                    "error": row.get("error", ""),
                    "progress_events": _parse_stored_progress_events(row.get("progress_json")),
                }
        except Exception:
            pass
    if not item:
        return JSONResponse({"ok": False, "error": "task not found"}, status_code=404)
    return JSONResponse({"ok": True, "task": _task_public(item) if isinstance(item, dict) else item})


@router.delete("/agent/tasks/{task_id}")
def cancel_background_task_delete(task_id: str):
    """Best-effort cooperative cancel: sets client_abort_event on the background run."""
    get_touch_activity()()
    return _cancel_background_task_impl(task_id)


@router.post("/agent/tasks/{task_id}/cancel")
def cancel_background_task_post(task_id: str):
    """Same as DELETE /agent/tasks/{task_id} — for clients that prefer POST."""
    get_touch_activity()()
    return _cancel_background_task_impl(task_id)
