"""
Mission system: long-running agent tasks with persistence.
Missions execute planner steps asynchronously via APScheduler worker.
"""
import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("layla")

MAX_MISSION_STEPS = 10
DEFAULT_MAX_MISSION_RUNTIME_SECONDS = 3600  # 1 hour


def create_mission(goal: str, workspace_root: str = "", allow_write: bool = False, allow_run: bool = False) -> dict | None:
    """
    Create a mission: generate plan, persist to DB, return mission dict.
    Mission starts as 'pending'; mission_worker will run it.
    """
    try:
        from layla.memory.db import save_mission, get_mission
        from services.planner import create_plan
        from services.observability import log_mission_created
    except ImportError as e:
        logger.warning("mission create imports failed: %s", e)
        return None
    if not goal or not goal.strip():
        return None
    plan = create_plan(goal, max_steps=MAX_MISSION_STEPS)
    if not plan:
        return None
    mission_id = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mission = {
        "id": mission_id,
        "goal": goal[:2000],
        "plan": plan,
        "status": "pending",
        "current_step": 0,
        "results": [],
        "created_at": now,
        "updated_at": now,
        "workspace_root": workspace_root or "",
        "allow_write": allow_write,
        "allow_run": allow_run,
    }
    try:
        save_mission(mission)
        log_mission_created(mission_id=mission_id, goal_preview=goal[:60], steps=len(plan))
        return mission
    except Exception as e:
        logger.warning("mission save failed: %s", e)
        return None


def run_mission(mission_id: str) -> bool:
    """Mark mission as running; mission_worker will pick it up."""
    try:
        from layla.memory.db import get_mission, update_mission_status
        from services.observability import log_mission_started
    except ImportError as e:
        logger.warning("mission run imports failed: %s", e)
        return False
    mission = get_mission(mission_id)
    if not mission:
        return False
    if mission.get("status") not in ("pending", "paused"):
        return False
    update_mission_status(mission_id, "running")
    log_mission_started(mission_id=mission_id, goal_preview=mission.get("goal", "")[:60])
    return True


def resume_mission(mission_id: str) -> bool:
    """Resume a paused or running mission; same as run_mission for worker."""
    return run_mission(mission_id)


def execute_next_step(mission_id: str) -> dict | None:
    """
    Execute the next step of a mission. Called by mission_worker.
    Returns updated mission or None on failure/completion.
    """
    try:
        from layla.memory.db import get_mission, update_mission_progress
        from agent_loop import autonomous_run
        from services.observability import log_mission_step, log_mission_completed, log_mission_failed
        import runtime_safety
    except ImportError as e:
        logger.warning("mission step imports failed: %s", e)
        return None
    mission = get_mission(mission_id)
    if not mission:
        return None
    if mission.get("status") != "running":
        return mission
    plan = mission.get("plan") or []
    current_step = int(mission.get("current_step", 0))
    results = list(mission.get("results") or [])
    cfg = runtime_safety.load_config()
    max_runtime = int(cfg.get("max_mission_runtime_seconds", DEFAULT_MAX_MISSION_RUNTIME_SECONDS))
    created_at = mission.get("created_at", "")
    try:
        created_ts = time.mktime(time.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        created_ts = time.time()
    if time.time() - created_ts > max_runtime:
        update_mission_progress(mission_id, status="failed", results=results + [{"step": current_step + 1, "error": "max_mission_runtime exceeded"}])
        log_mission_failed(mission_id=mission_id, reason="max_mission_runtime exceeded")
        return None
    if current_step >= len(plan) or current_step >= MAX_MISSION_STEPS:
        update_mission_progress(mission_id, status="completed", results=results)
        log_mission_completed(mission_id=mission_id, steps_done=len(results))
        return None
    step_def = plan[current_step]
    task = step_def.get("task", "")
    tools_hint = step_def.get("tools", [])
    step_goal = task
    if tools_hint:
        step_goal += f" (consider: {', '.join(tools_hint[:3])})"
    goal_prefix = (mission.get("goal") or "")[:100]
    if goal_prefix:
        step_goal = f"{goal_prefix}\n\nStep {step_def.get('step', current_step + 1)}: {step_goal}"
    workspace = mission.get("workspace_root", "") or cfg.get("sandbox_root", "")
    t0 = time.time()
    try:
        result = autonomous_run(
            step_goal,
            context="",
            workspace_root=workspace,
            allow_write=bool(mission.get("allow_write")),
            allow_run=bool(mission.get("allow_run")),
            conversation_history=[],
            aspect_id="morrigan",
            show_thinking=False,
            stream_final=False,
            research_mode=False,
            plan_depth=1,
        )
        elapsed_ms = (time.time() - t0) * 1000
        step_result = {
            "step": step_def.get("step", current_step + 1),
            "task": task,
            "result_status": result.get("status", ""),
            "elapsed_ms": round(elapsed_ms, 1),
        }
        results.append(step_result)
        log_mission_step(
            mission_id=mission_id,
            step=current_step + 1,
            task_preview=task[:60],
            status=result.get("status", ""),
            duration_ms=elapsed_ms,
        )
        next_step = current_step + 1
        if next_step >= len(plan) or next_step >= MAX_MISSION_STEPS:
            update_mission_progress(mission_id, status="completed", current_step=next_step, results=results)
            log_mission_completed(mission_id=mission_id, steps_done=len(results))
        else:
            update_mission_progress(mission_id, current_step=next_step, results=results)
        return get_mission(mission_id)
    except Exception as e:
        logger.exception("mission step failed: %s", e)
        results.append({"step": step_def.get("step", current_step + 1), "task": task, "result_status": "error", "error": str(e)})
        update_mission_progress(mission_id, status="failed", current_step=current_step + 1, results=results)
        log_mission_failed(mission_id=mission_id, reason=str(e))
        return None
