"""File-backed plan execution — delegates to engine_plans.run_plan_iteration."""
from __future__ import annotations

from typing import Any, Callable

from services.engine_plans import run_file_plan_background_loop, run_plan_iteration


def execute_next_step(workspace_root: str, plan_id: str) -> dict[str, Any]:
    import runtime_safety
    from services.plan_service import load_plan

    cfg = runtime_safety.load_config()
    p = load_plan(workspace_root, plan_id)
    payload: dict[str, Any] = {
        "workspace_root": workspace_root,
        "allow_write": bool(p.allow_write) if p else False,
        "allow_run": bool(p.allow_run) if p else False,
        "aspect_id": "morrigan",
        "conversation_id": "",
        "conversation_history": [],
    }
    return run_plan_iteration(
        workspace_root,
        plan_id,
        planning_strict_mode=bool(cfg.get("planning_strict_mode")),
        payload=payload,
    )


def execute_next_step_continuous_loop(
    task_id: str,
    payload: dict,
    client_abort: Any,
    progress_cb: Callable[[dict], None] | None,
    max_iter: int,
    delay_s: float,
) -> dict:
    """Background worker: purposeful iterations via engine (strict / draft / execute)."""
    return run_file_plan_background_loop(
        task_id,
        payload,
        client_abort,
        progress_cb,
        max_iter,
        delay_s,
    )
