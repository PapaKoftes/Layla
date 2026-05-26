"""Post-batch tool guards: policy enforcement, loop detection, args validation,
duplicate detection, and retry-constrained blocking.

Extracted from agent_loop._run_tool_guards to reduce module size.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def run_tool_guards(
    intent: str,
    decision: dict | None,
    state: dict,
    cfg: dict,
    goal: str,
    workspace: str,
    context: str,
    *,
    get_tools_for_goal_fn: Callable[..., frozenset],
    log_tool_outcome_fn: Callable[[str, object], None],
    format_steps_fn: Callable[[list], str],
    valid_tools: frozenset[str],
) -> tuple[bool, str]:
    """Run post-batch tool guards (policy, loop, args, dup, recovery).
    Returns (blocked, goal). If blocked, caller should continue the loop."""
    # OpenClaw-style tool policy: block execution outside effective tool set
    if intent not in ("reason", "finish", "wakeup") and intent in valid_tools:
        from services.tool_policy import tool_allowed

        _vt = get_tools_for_goal_fn(goal, context=context or "", workspace_root=workspace or "", state=state)
        try:
            if cfg.get("decision_policy_enabled", True):
                from services.decision_policy import apply_caps_to_valid_tools as _apply_caps_to_valid_tools
                from services.decision_policy import build_policy_caps as _build_policy_caps

                _cid = (state.get("conversation_id") or "").strip() or "unknown"
                _caps = _build_policy_caps(state, cfg, conversation_id=_cid)
                state["policy_caps"] = _caps.to_trace_dict()
                _vt = _apply_caps_to_valid_tools(_vt, _caps)
        except Exception as _dp_exc:
            logger.warning("decision_policy caps skipped at dispatch: %s", _dp_exc)
        if not tool_allowed(intent, _vt):
            state["tool_calls"] += 1
            _tpd = {
                "ok": False,
                "reason": "tool_policy_denied",
                "message": (
                    f"Tool {intent} is not allowed this turn "
                    "(tools_profile / tools_allow / tools_deny / intent filter)."
                ),
            }
            state["steps"].append({"action": intent, "result": _tpd})
            log_tool_outcome_fn(intent, _tpd)
            state["last_tool_used"] = intent
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + format_steps_fn(state["steps"])
            return True, goal

    if intent not in ("reason", "finish", "wakeup") and intent in valid_tools:
        try:
            from services.tool_loop_detection import push_and_evaluate

            _loop_ev = push_and_evaluate(
                cfg, state, intent, decision, reasoning_mode=state.get("reasoning_mode"),
            )
            if _loop_ev and _loop_ev.startswith("STOP:"):
                state["tool_calls"] += 1
                _tlr = {
                    "ok": False,
                    "reason": "tool_loop_detected",
                    "message": _loop_ev[5:].strip(),
                }
                state["steps"].append({"action": intent, "result": _tlr})
                log_tool_outcome_fn(intent, _tlr)
                state["last_tool_used"] = intent
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + format_steps_fn(state["steps"])
                return True, goal
            if _loop_ev and _loop_ev.startswith("WARN:"):
                state["tool_loop_prompt_hint"] = _loop_ev[5:].strip()
        except Exception as _exc:
            logger.warning("agent_loop:L3249: %s", _exc, exc_info=True)

    if intent not in ("reason", "finish", "wakeup") and intent in valid_tools:
        try:
            from services.tool_args import validate_tool_invocation

            _verr = validate_tool_invocation(intent, decision, goal, workspace)
            if _verr:
                state["tool_calls"] += 1
                state["steps"].append({"action": intent, "result": _verr})
                log_tool_outcome_fn(intent, _verr)
                state["last_tool_used"] = intent
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + format_steps_fn(state["steps"])
                return True, goal
        except Exception as _exc:
            logger.warning("agent_loop:L3264: %s", _exc, exc_info=True)

    if intent not in ("reason", "finish", "wakeup", "none") and intent in valid_tools:
        try:
            from services.tool_loop_detection import exact_call_key

            _eck = exact_call_key(intent, decision)
            _seen = state.setdefault("_recent_exact_calls", set())
            if _eck in _seen:
                state["tool_calls"] += 1
                _tdup = {
                    "ok": False,
                    "reason": "tool_loop_detected",
                    "message": "Exact duplicate tool invocation blocked for this run.",
                }
                state["steps"].append({"action": intent, "result": _tdup})
                log_tool_outcome_fn(intent, _tdup)
                state["last_tool_used"] = intent
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + format_steps_fn(state["steps"])
                return True, goal
        except Exception as _exc:
            logger.warning("agent_loop:L3285: %s", _exc, exc_info=True)

    if intent not in ("reason", "finish", "wakeup", "none") and intent in valid_tools:
        try:
            from services.failure_recovery import block_repeated_mutating_under_retry_constrained

            if block_repeated_mutating_under_retry_constrained(state, intent):
                state["tool_calls"] += 1
                _br = {
                    "ok": False,
                    "reason": "retry_constrained_block",
                    "message": (
                        "Same mutating tool blocked under retry_constrained; verify with read_file/grep before retrying."
                    ),
                }
                state["steps"].append({"action": intent, "result": _br})
                log_tool_outcome_fn(intent, _br)
                state["last_tool_used"] = intent
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + format_steps_fn(state["steps"])
                return True, goal
        except Exception as _exc:
            logger.warning("agent_loop:L3306: %s", _exc, exc_info=True)

    return False, goal
