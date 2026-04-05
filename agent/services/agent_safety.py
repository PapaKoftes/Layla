"""
Centralized agent safety gates (planning strict mode, per-step tool allowlist).
Call sites: agent_loop decision/tool dispatch; keep logic here to avoid drift.
"""
from __future__ import annotations

from typing import Any

from layla.tools.registry import TOOLS

_PLANNING_STRICT_EXCEPTION_DANGEROUS = frozenset({"scan_repo", "update_project_memory"})
_PLANNING_STRICT_RUN_TOOLS = frozenset({
    "shell",
    "run_python",
    "mcp_tools_call",
    "run_tests",
    "pip_install",
    "shell_session_start",
    "shell_session_manage",
    "git_add",
    "git_commit",
})


def planning_strict_refusal_message() -> str:
    return (
        "Mutating tools require an approved plan. Use plan_mode or POST /plans, "
        "POST /plans/{id}/approve, then pass plan_id on POST /agent or POST /plans/{id}/execute. "
        "Or set planning_strict_mode to false in runtime_config."
    )


def maybe_planning_strict_refusal(
    intent: str,
    cfg: dict,
    state: dict,
    allow_write: bool,
    allow_run: bool,
) -> dict | None:
    """When planning_strict_mode is on, block dangerous/run tools unless plan_approved."""
    if not cfg.get("planning_strict_mode"):
        return None
    if state.get("plan_approved"):
        return None
    if not (allow_write or allow_run):
        return None
    if intent in ("reason", "finish", "wakeup", "none"):
        return None
    meta = TOOLS.get(intent) or {}
    if intent in _PLANNING_STRICT_RUN_TOOLS:
        return {"ok": False, "reason": "planning_strict_mode", "message": planning_strict_refusal_message()}
    if meta.get("dangerous") and intent not in _PLANNING_STRICT_EXCEPTION_DANGEROUS:
        return {"ok": False, "reason": "planning_strict_mode", "message": planning_strict_refusal_message()}
    return None


def maybe_step_tool_allowlist_refusal(intent: str, _cfg: dict) -> dict | None:
    """When file-plan execution set a non-empty step.tools allowlist, reject any other tool."""
    if intent in ("reason", "finish", "wakeup", "none", "think"):
        return None
    try:
        from services.tool_allowlist_context import get_plan_step_tool_allowlist
    except Exception:
        return None
    al = get_plan_step_tool_allowlist()
    if not al or len(al) == 0:
        return None
    if intent not in al:
        allowed = ", ".join(sorted(al))
        return {
            "ok": False,
            "reason": "step_tool_allowlist",
            "message": (
                f"Tool {intent!r} is not allowed for this plan step. "
                f"Allowed: {allowed}. "
                "Adjust the step's tools[] list or clear it to allow any tool (subject to other gates)."
            ),
        }
    return None

