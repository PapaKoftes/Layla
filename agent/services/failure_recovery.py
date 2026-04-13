"""
Failure classification and recovery hints (North Star §8).
Structured recovery hints for planning_gap, execution_issue, workflow_breakdown.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")

_VERIFY_TOOLS = frozenset({"read_file", "list_dir", "write_file", "apply_patch", "shell", "grep_code", "glob_files", "git_status", "git_diff", "git_log", "git_branch"})

# Mutating tools for which repeating the same call without a verification step is blocked under retry_constrained.
_RETRY_CONSTRAINED_MUTATING = frozenset({"write_file", "run_python", "apply_patch", "shell"})


def block_repeated_mutating_under_retry_constrained(state: dict, intent: str) -> bool:
    """
    Runtime enforcement (North Star §8): same mutating tool again while stagnating under retry_constrained
    is refused so the loop must verify or change args/approach.
    """
    if str(state.get("recovery_strategy") or "") != "retry_constrained":
        return False
    if int(state.get("consecutive_no_progress") or 0) <= 0:
        return False
    last = state.get("last_tool_used")
    if not intent or intent != last:
        return False
    return intent in _RETRY_CONSTRAINED_MUTATING


def classify_failure_and_recovery(state: dict) -> None:
    """Classify failure type and set structured recovery hint (stringify at prompt assembly)."""
    consecutive = state.get("consecutive_no_progress", 0)
    if consecutive == 0:
        state.pop("recovery_hint", None)
        state.pop("recovery_strategy", None)
        return
    last_tool = state.get("last_tool_used") or ""
    if last_tool in ("read_file", "list_dir", "grep_code", "glob_files", "file_info", "get_project_context", "understand_file"):
        state["recovery_strategy"] = "replan"
        state["recovery_hint"] = {
            "type": "planning_gap",
            "recovery_strategy": "replan",
            "message": "Consider breaking the goal into smaller steps or asking the user to clarify. Try a different inspection or reply (reason).",
            "source": "failure_classifier",
        }
    elif last_tool in ("write_file", "run_python", "apply_patch", "shell"):
        state["recovery_strategy"] = "retry_constrained"
        state["recovery_hint"] = {
            "type": "execution_issue",
            "recovery_strategy": "retry_constrained",
            "message": "Execution may have failed or been blocked. Check tool result; suggest a fix or ask the user. Prefer read_file to verify state before retrying.",
            "source": "failure_classifier",
        }
    else:
        state["recovery_strategy"] = "escalate_user"
        state["recovery_hint"] = {
            "type": "workflow_breakdown",
            "recovery_strategy": "escalate_user",
            "message": "Workflow may be stuck. Consider replying (reason) to summarize what was tried and suggest next steps, or propose a revised objective.",
            "source": "failure_classifier",
        }


def format_recovery_hint_for_prompt(recovery_hint: dict) -> str:
    """Stringify structured recovery hint for injection into decision prompt."""
    if not recovery_hint or not isinstance(recovery_hint, dict):
        return ""
    t = recovery_hint.get("type") or ""
    msg = recovery_hint.get("message") or ""
    strat = str(recovery_hint.get("recovery_strategy") or "").strip()
    if not t and not msg:
        return ""
    next_step = ""
    if strat == "replan":
        next_step = "Next step: replan — break the goal into smaller steps or use create_plan before more tools."
    elif strat == "retry_constrained":
        next_step = "Next step: retry with constraints — verify with read_file/grep, then one minimal fix; avoid repeating the same failing tool args."
    elif strat == "escalate_user":
        next_step = "Next step: escalate — reply (reason) with a short summary and ask the user for direction or approval."
    parts = [f"Failure type: {t}. Assist recovery: {msg}"]
    if next_step:
        parts.append(next_step)
    return " ".join(parts) + " "
