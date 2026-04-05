"""Durable planning-first API: layla_plans in SQLite."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("layla")

router = APIRouter(prefix="/plans", tags=["plans"])


def _persist_plan_workspace_files(plan: dict) -> None:
    try:
        from services.plan_workspace_store import mirror_sqlite_plan

        mirror_sqlite_plan(plan)
    except Exception:
        pass


def _mirror_plan_to_workspace_memory(workspace_root: str, plan: dict) -> None:
    if not (workspace_root or "").strip():
        return
    try:
        from layla.tools.registry import inside_sandbox
        from services import project_memory as pm
        from services.engine_plans import mirror_plan_to_project_memory_patch

        root = Path(str(workspace_root).strip()).expanduser().resolve()
        if not root.is_dir() or not inside_sandbox(root):
            return
        patch = mirror_plan_to_project_memory_patch(plan)
        base = pm.load_project_memory(root) or pm.empty_document(str(root))
        merged = pm.merge_patch(base, patch, max_files=500, max_list=200)
        existing_plans = base.get("plans") if isinstance(base.get("plans"), list) else []
        new_entry = (patch.get("plans") or [{}])[0]
        plans_list = list(existing_plans) + [new_entry]
        maxp = 50
        if len(plans_list) > maxp:
            plans_list = plans_list[-maxp:]
        merged["plans"] = plans_list
        mb = 1_500_000
        pm.save_project_memory(root, merged, max_bytes=mb)
    except Exception as e:
        logger.debug("mirror_plan_to_workspace_memory: %s", e)


@router.post("")
async def create_plan(req: Request):
    body = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
    goal = (body or {}).get("goal") or (body or {}).get("message") or ""
    if not str(goal).strip():
        return JSONResponse({"ok": False, "error": "goal required"}, status_code=400)
    context = str((body or {}).get("context") or "")
    workspace_root = str((body or {}).get("workspace_root") or "")
    conversation_id = str((body or {}).get("conversation_id") or "")
    raw_steps = (body or {}).get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else None
    if steps is None:
        import runtime_safety
        from services.engine_plans import normalize_planner_steps
        from services.planner import create_plan as planner_create_plan

        cfg = runtime_safety.load_config()
        digest = ""
        if workspace_root.strip():
            try:
                from services.plan_workspace_store import prior_plans_digest

                digest = prior_plans_digest(workspace_root.strip(), limit=8)
            except Exception:
                digest = ""
        plan_steps = await asyncio.to_thread(
            planner_create_plan, str(goal).strip(), 6, cfg, digest
        )
        steps = normalize_planner_steps(plan_steps)
    else:
        from services.engine_plans import normalize_planner_steps

        steps = normalize_planner_steps([s for s in steps if isinstance(s, dict)])
    from layla.memory.db import create_layla_plan, get_layla_plan

    pid = create_layla_plan(
        str(goal).strip(),
        context=context,
        steps=steps,
        workspace_root=workspace_root,
        conversation_id=conversation_id,
        status="draft",
    )
    pnew = get_layla_plan(pid)
    if pnew:
        _persist_plan_workspace_files(pnew)
    return JSONResponse({"ok": True, "plan_id": pid, "status": "draft", "steps": steps, "goal": goal})


@router.get("")
def list_plans(workspace_root: str | None = None, status: str = "", limit: int = 50):
    from layla.memory.db import list_layla_plans

    wr = (workspace_root or "").strip() or None
    st = status.strip() or None
    items = list_layla_plans(workspace_root=wr, status=st, limit=limit)
    return JSONResponse({"ok": True, "plans": items})


@router.get("/{plan_id}")
def get_plan(plan_id: str):
    from layla.memory.db import get_layla_plan

    p = get_layla_plan(plan_id)
    if not p:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    return JSONResponse({"ok": True, "plan": p})


@router.patch("/{plan_id}")
async def patch_plan(plan_id: str, req: Request):
    body = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
    from layla.memory.db import get_layla_plan, update_layla_plan

    existing = get_layla_plan(plan_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    if existing["status"] in ("executing", "done"):
        return JSONResponse({"ok": False, "error": "plan_not_editable"}, status_code=409)
    goal = body.get("goal")
    context = body.get("context")
    status = body.get("status")
    steps = body.get("steps")
    if steps is not None and not isinstance(steps, list):
        return JSONResponse({"ok": False, "error": "steps must be a list"}, status_code=400)
    if steps is not None:
        from services.engine_plans import normalize_planner_steps

        steps = normalize_planner_steps([s for s in steps if isinstance(s, dict)])
    ok = update_layla_plan(
        plan_id,
        goal=goal if isinstance(goal, str) else None,
        context=context if isinstance(context, str) else None,
        steps=steps,
        status=status if isinstance(status, str) else None,
    )
    if not ok:
        return JSONResponse({"ok": False, "error": "update_failed"}, status_code=500)
    p = get_layla_plan(plan_id)
    if p:
        _persist_plan_workspace_files(p)
    sug: list[str] = []
    if steps is not None:
        from services.plan_step_governance import suggest_sqlite_plan_improvements

        sug = suggest_sqlite_plan_improvements(p.get("steps") or [])
    body: dict = {"ok": True, "plan": p}
    if sug:
        body["suggestions"] = sug
    return JSONResponse(body)


@router.post("/{plan_id}/approve")
def approve_plan(plan_id: str):
    from layla.memory.db import approve_layla_plan, get_layla_plan
    from services.plan_step_governance import validate_sqlite_plan_before_approval

    p0 = get_layla_plan(plan_id)
    if not p0:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    v_errs = validate_sqlite_plan_before_approval(p0)
    if v_errs:
        return JSONResponse({"ok": False, "error": "plan_validation_failed", "details": v_errs}, status_code=400)
    if not approve_layla_plan(plan_id):
        return JSONResponse({"ok": False, "error": "approve_failed"}, status_code=400)
    p = get_layla_plan(plan_id)
    if p:
        _persist_plan_workspace_files(p)
        _mirror_plan_to_workspace_memory(p.get("workspace_root") or "", p)
    return JSONResponse({"ok": True, "plan": p})


@router.post("/{plan_id}/execute")
async def execute_stored_plan(plan_id: str, req: Request):
    body = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
    from layla.memory.db import get_layla_plan, set_layla_plan_status

    p = get_layla_plan(plan_id)
    if not p:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    if p["status"] != "approved":
        return JSONResponse(
            {"ok": False, "error": "plan_not_approved", "detail": "Approve the plan first (POST /plans/{id}/approve)."},
            status_code=409,
        )
    allow_write = (body or {}).get("allow_write") is True
    allow_run = (body or {}).get("allow_run") is True
    workspace_root = str((body or {}).get("workspace_root") or p.get("workspace_root") or "")
    aspect_id = str((body or {}).get("aspect_id") or "morrigan")
    conversation_id = str((body or {}).get("conversation_id") or p.get("conversation_id") or "")
    try:
        dm = int((body or {}).get("default_max_retries") or (body or {}).get("step_max_retries") or 1)
    except (TypeError, ValueError):
        dm = 1
    dm = max(0, min(3, dm))
    from services.engine_plans import steps_for_planner_execution
    from services.planner import execute_plan as _exec_plan

    exec_steps = steps_for_planner_execution(p.get("steps") or [])
    if not exec_steps:
        return JSONResponse({"ok": False, "error": "no_steps"}, status_code=400)
    set_layla_plan_status(plan_id, "executing")
    p_run = get_layla_plan(plan_id)
    if p_run:
        _persist_plan_workspace_files(p_run)
    from agent_loop import autonomous_run

    try:
        results = await asyncio.to_thread(
            _exec_plan,
            exec_steps,
            autonomous_run,
            "",
            0,
            step_governance=True,
            default_max_retries=dm,
            context=p.get("context") or "",
            workspace_root=workspace_root,
            allow_write=allow_write,
            allow_run=allow_run,
            aspect_id=aspect_id,
            conversation_id=conversation_id,
            active_plan_id=plan_id,
            plan_approved=True,
        )
        all_ok = bool(results.get("all_steps_ok"))
        set_layla_plan_status(plan_id, "done" if all_ok else "blocked")
        p_done = get_layla_plan(plan_id)
        if p_done:
            _persist_plan_workspace_files(p_done)
            try:
                from services.plan_workspace_store import append_plan_history

                append_plan_history(
                    p_done.get("workspace_root") or workspace_root,
                    {
                        "plan_id": plan_id,
                        "source": "sqlite",
                        "outcome": "done" if all_ok else "blocked",
                        "goal_preview": (p_done.get("goal") or "")[:300],
                    },
                )
            except Exception:
                pass
        return JSONResponse(
            {
                "ok": True,
                "status": "plan_executed",
                "results": results,
                "plan_id": plan_id,
                "all_steps_ok": all_ok,
            }
        )
    except Exception as e:
        logger.exception("execute_stored_plan")
        set_layla_plan_status(plan_id, "approved")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
