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
    from layla.memory.plans_db import update_layla_plan_steps

    def _persist_step_progress(merged_steps: list) -> None:
        try:
            if update_layla_plan_steps(plan_id, merged_steps):
                p2 = get_layla_plan(plan_id)
                if p2:
                    _persist_plan_workspace_files(p2)
        except Exception:
            pass

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
            progress_callback=_persist_step_progress,
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


# ── Phase 2.1: Plan Gantt visualization data ─────────────────────────────────

_TOOL_DURATION_MS: dict[str, int] = {
    "read_file": 400, "list_directory": 300, "search_files": 600,
    "write_file": 800, "edit_file": 700, "create_file": 700,
    "run_command": 3000, "execute_command": 3000, "bash": 3000,
    "web_search": 2000, "web_fetch": 2500,
    "read_webpage": 2000,
}
_DEFAULT_STEP_MS = 2500
_ANALYSIS_KEYWORDS = {"analyze", "review", "understand", "summarize", "explain", "plan", "research"}


def _estimate_step_duration(step: dict) -> int:
    """Estimate step duration in ms based on tools or description keywords."""
    tools: list[str] = step.get("tools") or []
    if tools:
        return max(_TOOL_DURATION_MS.get(t.lower(), _DEFAULT_STEP_MS) for t in tools)
    desc = (step.get("task") or step.get("description") or "").lower()
    if any(k in desc for k in _ANALYSIS_KEYWORDS):
        return 5000
    return _DEFAULT_STEP_MS


@router.get("/{plan_id}/viz")
def get_plan_viz(plan_id: str):
    """
    Return enriched plan data for Gantt visualization.
    Adds estimated_duration_ms, depends_on, parallel_capable, and total_estimated_ms.
    """
    from layla.memory.db import get_layla_plan

    p = get_layla_plan(plan_id)
    if not p:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)

    raw_steps: list[dict] = p.get("steps") or []
    viz_steps = []
    for i, s in enumerate(raw_steps):
        est = int(s.get("estimated_duration_ms") or _estimate_step_duration(s))
        depends_on: list[int] = list(s.get("depends_on") or ([] if i == 0 else [i - 1]))
        viz_steps.append({
            "index": i,
            "task": (s.get("task") or s.get("description") or f"Step {i + 1}")[:120],
            "tools": s.get("tools") or [],
            "type": s.get("type") or "task",
            "status": s.get("status") or "pending",
            "estimated_duration_ms": est,
            "depends_on": depends_on,
        })

    total_ms = sum(s["estimated_duration_ms"] for s in viz_steps)
    # Detect parallel capable: any step that depends on the same predecessor
    dep_counts: dict[int, int] = {}
    for s in viz_steps:
        for d in s["depends_on"]:
            dep_counts[d] = dep_counts.get(d, 0) + 1
    parallel_capable = any(v > 1 for v in dep_counts.values())

    return JSONResponse({
        "ok": True,
        "plan_id": plan_id,
        "goal": p.get("goal") or "",
        "status": p.get("status") or "draft",
        "steps": viz_steps,
        "total_estimated_ms": total_ms,
        "parallel_capable": parallel_capable,
    })


@router.get("/similar")
def find_similar_plans(goal: str = "", limit: int = 5):
    """
    Return up to `limit` historical plans whose goal is similar to `goal`.
    Uses simple keyword overlap; returns done/blocked plans only.
    """
    from layla.memory.db import list_layla_plans

    if not goal.strip():
        return JSONResponse({"ok": True, "similar": []})

    q_words = set(goal.lower().split())
    candidates = list_layla_plans(status=None, limit=200)
    scored: list[tuple[float, dict]] = []
    for p in candidates:
        if p.get("status") not in ("done", "blocked"):
            continue
        p_words = set((p.get("goal") or "").lower().split())
        if not p_words:
            continue
        overlap = len(q_words & p_words) / max(len(q_words | p_words), 1)
        if overlap > 0:
            scored.append((overlap, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    similar = []
    for score, p in scored[:limit]:
        similar.append({
            "plan_id": p.get("id"),
            "goal": (p.get("goal") or "")[:200],
            "status": p.get("status") or "",
            "step_count": len(p.get("steps") or []),
            "created_at": p.get("created_at") or "",
            "similarity": round(score, 3),
        })
    return JSONResponse({"ok": True, "similar": similar})
