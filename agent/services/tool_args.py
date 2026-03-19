"""
Validate tool `args` from structured LLM decisions before dispatch.
Returns None if OK; otherwise an error dict for the agent loop (ok: False).
Gated by runtime_config tool_args_validation_enabled (default True).
"""
from __future__ import annotations

from typing import Any

# Per-tool: required keys and expected types (value must be instance or None for optional)
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "git_commit": {
        "required": ["message"],
        "types": {"message": str, "repo": str, "add_all": bool},
    },
    "search_codebase": {
        "required": ["symbol"],
        "types": {"symbol": str, "root": str},
    },
    "vector_search": {
        "required": ["query"],
        "types": {"query": str, "collection": str, "k": int},
    },
    "shell": {
        "required": ["argv"],
        "types": {"argv": list, "cwd": str},
    },
    "run_tests": {
        "required": [],
        "types": {"cwd": str, "pattern": str, "extra_args": str, "timeout_s": int},
    },
    "pip_install": {
        "required": ["packages"],
        "types": {"packages": (str, list), "cwd": str},
    },
}


def validate_tool_args(tool_name: str, args: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    If validation fails, return {"ok": False, "error": "tool_args_validation_failed", "message": "..."}.
    """
    try:
        import runtime_safety

        if not runtime_safety.load_config().get("tool_args_validation_enabled", True):
            return None
    except Exception:
        return None
    schema = TOOL_SCHEMAS.get(tool_name)
    if not schema:
        return None
    if not isinstance(args, dict):
        return {
            "ok": False,
            "error": "tool_args_validation_failed",
            "message": f"{tool_name}: args must be an object",
        }
    req = schema.get("required") or []
    for key in req:
        val = args.get(key)
        if val is None:
            return {
                "ok": False,
                "error": "tool_args_validation_failed",
                "message": f"{tool_name}: missing required arg '{key}'",
            }
        if isinstance(val, str) and not val.strip():
            return {
                "ok": False,
                "error": "tool_args_validation_failed",
                "message": f"{tool_name}: empty required arg '{key}'",
            }
        if key == "argv" and isinstance(val, list):
            if not val:
                return {
                    "ok": False,
                    "error": "tool_args_validation_failed",
                    "message": f"{tool_name}: argv must be non-empty list",
                }
            if not all(isinstance(x, str) for x in val):
                return {
                    "ok": False,
                    "error": "tool_args_validation_failed",
                    "message": f"{tool_name}: argv must be a list of strings",
                }
    types_map = schema.get("types") or {}
    for key, expected in types_map.items():
        if key not in args:
            continue
        val = args[key]
        if val is None:
            continue
        if isinstance(expected, tuple):
            if not isinstance(val, expected):
                return {
                    "ok": False,
                    "error": "tool_args_validation_failed",
                    "message": f"{tool_name}: arg '{key}' has wrong type",
                }
        elif not isinstance(val, expected):
            return {
                "ok": False,
                "error": "tool_args_validation_failed",
                "message": f"{tool_name}: arg '{key}' must be {expected.__name__}",
            }
    return None


def validate_tool_invocation(
    intent: str,
    decision: dict[str, Any] | None,
    goal: str,
    workspace: str,
) -> dict[str, Any] | None:
    """Only validate when model supplied non-empty args (structured tool calling)."""
    if not decision or intent in ("reason", "finish", "wakeup"):
        return None
    args = decision.get("args")
    if not isinstance(args, dict) or not args:
        return None
    return validate_tool_args(intent, args)
