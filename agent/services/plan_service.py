"""File-backed plan CRUD under `{workspace}/.layla_plans/` (separate from SQLite `/plans` API)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from layla.tools.registry import inside_sandbox
from services.plan_schema import Plan, PlanStep

logger = logging.getLogger("layla")

PLANS_DIR_NAME = ".layla_plans"


def _workspace_path(workspace_root: str) -> Path | None:
    raw = (workspace_root or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    if not root.is_dir() or not inside_sandbox(root):
        return None
    return root


def _plans_dir(workspace_root: Path) -> Path:
    d = workspace_root / PLANS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plan_path(workspace_root: Path, plan_id: str) -> Path:
    safe_id = plan_id.replace("/", "").replace("\\", "")[:128]
    return _plans_dir(workspace_root) / f"{safe_id}.json"


def touch_updated(plan: Plan) -> None:
    from datetime import datetime, timezone

    plan.updated_at = datetime.now(timezone.utc).isoformat()


def save_plan(workspace_root: str, plan: Plan) -> tuple[bool, str]:
    root = _workspace_path(workspace_root)
    if root is None:
        return False, "invalid_or_unsandboxed_workspace"
    touch_updated(plan)
    plan.workspace_root = str(root)
    p = _plan_path(root, plan.id)
    try:
        p.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    except OSError as e:
        return False, str(e)
    try:
        from services.plan_workspace_store import mirror_file_plan_json

        mirror_file_plan_json(str(root), plan.id, json.loads(plan.model_dump_json()))
    except Exception:
        pass
    return True, ""


def load_plan(workspace_root: str, plan_id: str) -> Plan | None:
    root = _workspace_path(workspace_root)
    if root is None:
        return None
    p = _plan_path(root, plan_id)
    if not p.is_file():
        return None
    try:
        return Plan.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("load_plan failed: %s", e)
        return None


def create_plan(workspace_root: str, goal: str, context: str = "") -> tuple[Plan | None, str]:
    from services import project_memory as pm

    root = _workspace_path(workspace_root)
    if root is None:
        return None, "invalid_or_unsandboxed_workspace"
    mem = pm.load_project_memory(root) or pm.empty_document(str(root))
    plan = Plan(goal=goal or "", context=context or "", workspace_root=str(root))
    plan.memory_summary = pm.summarize_memory(mem)
    st = mem.get("structure") if isinstance(mem.get("structure"), dict) else {}
    top = st.get("top_level_dirs") if isinstance(st.get("top_level_dirs"), list) else []
    if top:
        plan.repo_map_summary = ", ".join(str(x) for x in top[:20])[:800]
    ok, err = save_plan(str(root), plan)
    if not ok:
        return None, err or "save_failed"
    return plan, ""


def approve_plan(workspace_root: str, plan_id: str) -> tuple[Plan | None, str, list[str]]:
    from services.plan_step_governance import validate_file_plan_before_approval

    plan = load_plan(workspace_root, plan_id)
    if plan is None:
        return None, "plan_not_found", []
    v_errs = validate_file_plan_before_approval(plan)
    if v_errs:
        return None, "plan_validation_failed", v_errs
    plan.status = "approved"
    ok, err = save_plan(workspace_root, plan)
    if not ok:
        return None, err or "save_failed", []
    return plan, "", []


def set_step_status(plan: Plan, step_id: str, status: str) -> bool:
    for s in plan.steps:
        if s.id == step_id:
            s.status = status  # type: ignore[assignment]
            return True
    return False


def add_steps(plan: Plan, steps: list[PlanStep]) -> None:
    plan.steps.extend(steps)
