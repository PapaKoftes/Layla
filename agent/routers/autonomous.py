"""Autonomous research: Tier-0-only planner loop. Mounted at / by main."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import runtime_safety
from autonomous.controller import run_autonomous_task
from autonomous.types import AutonomousTask
from services.agent_task_runner import (
    _append_progress_event,
    finalize_inline_progress_task,
    register_inline_progress_task,
)

logger = logging.getLogger("layla")
router = APIRouter(tags=["autonomous"])


def _is_localhost(host: str | None) -> bool:
    if not host:
        return True
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1", "testclient")


def _remote_allowed_paths(cfg: dict) -> list[str]:
    """Match main.py remote allowlist behavior (copied intentionally, minimal)."""
    explicit = cfg.get("remote_allow_endpoints") or []
    if isinstance(explicit, list) and len(explicit) > 0:
        return [str(p).strip() for p in explicit if p]
    mode = (cfg.get("remote_mode") or "observe").strip().lower()
    if mode == "interactive":
        # main.py has a broader list; we only need to know if /autonomous/run would be permitted.
        return []  # not enabled by default
    return ["/wakeup", "/project_discovery", "/health"]


@router.post("/autonomous/run")
async def autonomous_run(request: Request):
    try:
        req = await request.json()
    except Exception:
        req = {}

    cfg = runtime_safety.load_config()
    if not cfg.get("autonomous_mode", False):
        return JSONResponse({"ok": False, "error": "autonomous_mode_disabled"}, status_code=403)

    confirm = bool((req or {}).get("confirm_autonomous", False)) if isinstance(req, dict) else False
    if not confirm:
        return JSONResponse({"ok": False, "error": "confirm_autonomous_required"}, status_code=400)

    client_host = request.client.host if request.client else None
    if not _is_localhost(client_host):
        if not cfg.get("remote_enabled"):
            return JSONResponse({"ok": False, "error": "local_only"}, status_code=403)
        allowed = _remote_allowed_paths(cfg)
        path = (request.url.path or "").strip()
        ok = any(path == p or path.startswith(p.rstrip("/") + "/") or path == p.rstrip("/") for p in allowed)
        if not ok:
            return JSONResponse({"ok": False, "error": "remote_forbidden"}, status_code=403)

    goal = ((req or {}).get("goal") or "").strip() if isinstance(req, dict) else ""
    if not goal:
        return JSONResponse({"ok": False, "error": "missing_goal"}, status_code=400)

    workspace_root = ((req or {}).get("workspace_root") or "").strip() if isinstance(req, dict) else ""
    if not workspace_root:
        workspace_root = str(Path.cwd())

    max_steps = int((req or {}).get("max_steps") or cfg.get("autonomous_max_steps") or 50)
    timeout_seconds = int((req or {}).get("timeout_seconds") or cfg.get("autonomous_timeout_seconds") or 60)
    research_mode = bool((req or {}).get("research_mode", False)) if isinstance(req, dict) else False

    allow_write = bool(cfg.get("autonomous_wiki_enabled")) and bool(cfg.get("autonomous_wiki_export_enabled"))

    task = AutonomousTask(
        goal=goal,
        workspace_root=workspace_root,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        confirm_autonomous=True,
        allow_write=allow_write,
        research_mode=research_mode,
        allow_network=False,
    )

    stream_tid = str((req or {}).get("progress_task_id") or "").strip() if isinstance(req, dict) else ""
    hook = None
    if stream_tid:

        def _hook(tool: str, args: object) -> None:
            if not isinstance(args, dict):
                args = {"_value": str(args)[:800]}
            try:
                preview = json.dumps(args, default=str)[:1500]
            except Exception:
                preview = str(args)[:1500]
            _append_progress_event(
                stream_tid,
                {"kind": "autonomous_tool", "tool": tool, "args_preview": preview},
            )

        hook = _hook

    result: dict | None = None
    err_msg: str | None = None
    if stream_tid:
        register_inline_progress_task(stream_tid, goal=goal[:8000], kind="autonomous_tier0")
    try:
        result = run_autonomous_task(task=task, cfg=cfg, tool_call_hook=hook)
        return JSONResponse(result)
    except Exception as e:
        err_msg = str(e)
        logger.exception("autonomous_run failed: %s", e)
        return JSONResponse({"ok": False, "error": err_msg}, status_code=500)
    finally:
        if stream_tid:
            finalize_inline_progress_task(stream_tid, result=result, error=err_msg)

