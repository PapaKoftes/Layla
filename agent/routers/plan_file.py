"""File-backed structured plans under `.layla_plans/` (REST: `/plan/*`)."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/plan", tags=["plan-file"])


@router.post("/create")
async def plan_create(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    body = body or {}
    ws = str(body.get("workspace_root") or "").strip()
    goal = str(body.get("goal") or "")
    ctx = str(body.get("context") or "")
    if not ws:
        return JSONResponse({"ok": False, "error": "workspace_root required"}, status_code=400)
    from services.plan_service import create_plan

    plan, err = create_plan(ws, goal, ctx)
    if plan is None:
        return JSONResponse({"ok": False, "error": err or "create_failed"}, status_code=400)
    return JSONResponse({"ok": True, "plan": plan.model_dump(mode="json")})


@router.get("/{plan_id}")
def plan_get(plan_id: str, workspace_root: str = Query("", alias="workspace_root")):
    ws = (workspace_root or "").strip()
    if not ws:
        return JSONResponse({"ok": False, "error": "workspace_root query required"}, status_code=400)
    from services.plan_service import load_plan

    p = load_plan(ws, plan_id)
    return JSONResponse({"ok": True, "plan": p.model_dump(mode="json") if p else None})


@router.post("/{plan_id}/approve")
def plan_approve(plan_id: str, workspace_root: str = Query("", alias="workspace_root")):
    ws = (workspace_root or "").strip()
    if not ws:
        return JSONResponse({"ok": False, "error": "workspace_root query required"}, status_code=400)
    from services.plan_service import approve_plan

    p, err, details = approve_plan(ws, plan_id)
    if p is None:
        code = 404 if err == "plan_not_found" else 400
        body: dict = {"ok": False, "error": err or "approve_failed"}
        if details:
            body["details"] = details
        return JSONResponse(body, status_code=code)
    return JSONResponse({"ok": True, "plan": p.model_dump(mode="json")})


@router.post("/{plan_id}/add_steps")
async def plan_add_steps(plan_id: str, request: Request, workspace_root: str = Query("", alias="workspace_root")):
    ws = (workspace_root or "").strip()
    if not ws:
        return JSONResponse({"ok": False, "error": "workspace_root query required"}, status_code=400)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    body = body or {}
    from services.plan_schema import PlanStep
    from services.plan_service import load_plan, save_plan, touch_updated

    p = load_plan(ws, plan_id)
    if p is None:
        return JSONResponse({"ok": False, "error": "plan_not_found"}, status_code=404)
    raw_steps = body.get("steps") or []
    if not isinstance(raw_steps, list):
        return JSONResponse({"ok": False, "error": "steps must be a list"}, status_code=400)
    try:
        for s in raw_steps:
            if not isinstance(s, dict):
                continue
            p.steps.append(PlanStep.model_validate(s))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"invalid_step: {e}"}, status_code=400)
    touch_updated(p)
    ok, err = save_plan(ws, p)
    if not ok:
        return JSONResponse({"ok": False, "error": err or "save_failed"}, status_code=500)
    return JSONResponse({"ok": True, "plan": p.model_dump(mode="json")})


@router.post("/{plan_id}/execute_next")
def plan_execute_next(plan_id: str, workspace_root: str = Query("", alias="workspace_root")):
    ws = (workspace_root or "").strip()
    if not ws:
        return JSONResponse({"ok": False, "error": "workspace_root query required"}, status_code=400)
    from services.plan_executor import execute_next_step

    return JSONResponse(execute_next_step(ws, plan_id))


@router.post("/{plan_id}/run_continuous")
async def plan_run_continuous(plan_id: str, request: Request, workspace_root: str = Query("", alias="workspace_root")):
    ws = (workspace_root or "").strip()
    if not ws:
        return JSONResponse({"ok": False, "error": "workspace_root query required"}, status_code=400)
    from services.plan_service import load_plan

    pl = load_plan(ws, plan_id)
    if pl is None:
        return JSONResponse({"ok": False, "error": "plan_not_found"}, status_code=404)
    if pl.status != "approved":
        return JSONResponse(
            {"ok": False, "error": "plan_must_be_approved", "status": pl.status},
            status_code=400,
        )

    import runtime_safety

    cfg = runtime_safety.load_config()
    if bool(cfg.get("background_use_subprocess_workers")):
        return JSONResponse(
            {
                "ok": False,
                "error": "file_plan_continuous_requires_thread_workers",
                "hint": "Set background_use_subprocess_workers to false for file-plan step runner.",
            },
            status_code=400,
        )

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    body = body or {}

    from routers.agent import PRIORITY_BACKGROUND, enqueue_threaded_autonomous

    out = enqueue_threaded_autonomous(
        {
            "message": f"[file-plan:{plan_id}] structured step execution",
            "workspace_root": ws,
            "allow_write": body.get("allow_write") is True,
            "allow_run": body.get("allow_run") is True,
            "continuous": True,
            "max_iterations": int(body.get("max_iterations") or 50),
            "iteration_delay_seconds": float(body.get("iteration_delay_seconds") or 1.0),
            "file_plan_step_mode": True,
            "file_plan_id": plan_id,
            "aspect_id": str(body.get("aspect_id") or "morrigan"),
        },
        default_priority=PRIORITY_BACKGROUND,
        kind="file_plan",
    )
    if not out.get("ok"):
        return JSONResponse(out, status_code=400)
    return JSONResponse({"ok": True, **out, "file_plan_id": plan_id})
