"""
Tool argument normalization and dispatch helpers for the agent loop.

Extracted from agent_loop.py — Phase 2 decomposition.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("layla")


def normalize_mcp_tool_args(args: dict) -> dict:
    """Map common model arg aliases onto mcp_tools_call parameters."""
    a = dict(args)
    if not (a.get("mcp_server") or "").strip() and (a.get("server") or "").strip():
        a["mcp_server"] = str(a.get("server") or "").strip()
    if not (a.get("tool_name") or "").strip() and (a.get("tool") or "").strip():
        a["tool_name"] = str(a.get("tool") or "").strip()
    return a


def inject_workspace_args(tool_name: str, args: dict, workspace: str) -> dict:
    """Add workspace/cwd/repo to args for tools that expect them (used by batch runner)."""
    args = dict(args)
    if "cwd" not in args and tool_name in ("run_tests", "pip_install", "pip_list", "shell_session_start", "shell_session_manage"):
        args["cwd"] = workspace
    if "repo" not in args and tool_name.startswith("git_"):
        args["repo"] = workspace
    if "root" not in args and tool_name in ("search_replace", "rename_symbol", "search_codebase"):
        args["root"] = workspace
    return args


def inject_cancel_message(conversation_history: list, tool_name: str, reason: str = "cancelled") -> None:
    """Inject a synthetic user message when a tool is cancelled/timed-out.
    Prevents the model from hallucinating tool results on the next turn (D5 pattern)."""
    try:
        msg = (
            f"[Tool execution cancelled: {tool_name} was {reason} by operator. "
            "Please continue your reasoning without that result. "
            "Do not assume the tool succeeded or guess its output.]"
        )
        conversation_history.append({"role": "user", "content": msg})
        try:
            from layla.memory.db import log_audit
            log_audit(tool_name, f"cancel:{reason}", "agent_loop", False)
        except Exception as _exc:
            logger.debug("inject_cancel_message audit: %s", _exc, exc_info=False)
        logger.info("cancel synthetic message injected for tool=%s reason=%s", tool_name, reason)
    except Exception as e:
        logger.debug("inject_cancel_message failed: %s", e)


def register_exact_tool_call(state: dict, intent: str, decision: dict | None) -> None:
    """Track tool usage in state for loop detection and observability."""
    if intent in ("reason", "finish", "wakeup", "none"):
        return
    state["tool_attempted_this_turn"] = True
    try:
        tu = state.setdefault("tools_used", [])
        if intent and intent not in tu:
            tu.append(intent)
    except Exception as e:
        logger.debug("tools_used tracking failed: %s", e, exc_info=True)
    try:
        from services.tool_loop_detection import exact_call_key
        state.setdefault("_recent_exact_calls", set()).add(exact_call_key(intent, decision))
    except Exception as _exc:
        logger.debug("register_exact_tool_call: %s", _exc, exc_info=False)


def apply_lite_mode_overrides(cfg: dict) -> dict:
    """
    Apply performance_mode-based lite overrides.
    Does NOT mutate the input dict; returns a shallow copy with adjusted keys.
    """
    import copy as _copy
    cfg = _copy.copy(cfg)
    pm = (cfg.get("performance_mode") or "auto").strip().lower()
    if pm == "low":
        cfg["max_tool_calls"] = min(int(cfg.get("max_tool_calls") or 5), 2)
        cfg["enable_cognitive_workspace"] = False
        cfg["planning_enabled"] = False
        cfg["retrieval_k"] = 3
        cfg["skip_deliberation"] = True
        cfg["skip_self_reflection"] = True
    elif pm == "mid":
        cfg["max_tool_calls"] = min(int(cfg.get("max_tool_calls") or 5), 4)
        cfg["enable_cognitive_workspace"] = False
        cfg["planning_enabled"] = cfg.get("planning_enabled", True)
    return cfg


def get_effective_config(base_cfg: dict) -> dict:
    """Apply system_optimizer runtime overrides. Never persists to disk."""
    try:
        from services.system_optimizer import get_runtime_overrides
        overrides = get_runtime_overrides()
        if overrides:
            cfg = dict(base_cfg)
            cfg.update(overrides)
            return cfg
    except Exception:
        pass
    return base_cfg


def path_under_lab(path: str | Path, lab_root: str) -> bool:
    """True if *path* is inside the research lab directory tree."""
    try:
        return Path(path).resolve().is_relative_to(Path(lab_root).resolve())
    except Exception:
        return False


def research_response_asks_user(text: str) -> bool:
    """Heuristic: does the assistant's response ask the user a question?"""
    import re
    if not text or not text.strip():
        return False
    t = text.strip()[-800:]
    return bool(
        re.search(r"\?\s*$", t, re.MULTILINE)
        or re.search(r"(?:would you|could you|shall I|should I|do you want|let me know)", t, re.IGNORECASE)
    )
