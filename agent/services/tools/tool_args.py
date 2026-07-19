"""
Validate tool `args` from structured LLM decisions before dispatch.
Returns None if OK; otherwise an error dict for the agent loop (ok: False).
Gated by runtime_config tool_args_validation_enabled (default True).
"""
from __future__ import annotations

from typing import Any

# Per-tool: required keys and expected types (value must be instance or None for optional).
# Every tool marked "dangerous: True" in domain manifests MUST have an entry here.
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── shell / system ───────────────────────────────────────────────────
    "shell": {
        "required": ["argv"],
        "types": {"argv": list, "cwd": str},
    },
    "shell_session_start": {
        "required": [],
        "types": {"argv": list, "cwd": str},
    },
    "pip_install": {
        "required": ["packages"],
        "types": {"packages": (str, list), "cwd": str},
    },
    "docker_run": {
        "required": ["image"],
        "types": {"image": str, "args": str, "name": str, "rm": bool},
    },
    # ── filesystem write ─────────────────────────────────────────────────
    "write_file": {
        "required": ["path", "content"],
        "types": {"path": str, "content": str},
    },
    "write_files_batch": {
        "required": ["files"],
        "types": {"files": list},
    },
    "search_replace": {
        "required": ["root", "find", "replace"],
        "types": {"root": str, "find": str, "replace": str,
                  "file_glob": str, "dry_run": bool},
    },
    "replace_in_file": {
        "required": ["path", "old_text", "new_text"],
        "types": {"path": str, "old_text": str, "new_text": str, "count": int},
    },
    "apply_patch": {
        "required": ["original_path", "patch_text"],
        "types": {"original_path": str, "patch_text": str},
    },
    "write_csv": {
        "required": ["path", "rows"],
        "types": {"path": str, "rows": list, "headers": list},
    },
    "restore_file_checkpoint": {
        "required": ["checkpoint_id"],
        "types": {"checkpoint_id": str},
    },
    "scan_repo": {
        "required": [],
        "types": {"workspace_root": str, "dry_run": bool, "max_files": int},
    },
    "update_project_memory": {
        "required": [],
        "types": {"workspace_root": str, "patch": dict},
    },
    # ── code execution ───────────────────────────────────────────────────
    "run_python": {
        "required": ["code", "cwd"],
        "types": {"code": str, "cwd": str},
    },
    "run_tests": {
        "required": [],
        "types": {"cwd": str, "pattern": str, "extra_args": str, "timeout_s": int},
    },
    "rename_symbol": {
        "required": ["root", "old_name", "new_name"],
        "types": {"root": str, "old_name": str, "new_name": str,
                  "symbol_type": str, "file_glob": str, "apply": bool},
    },
    "code_format": {
        "required": ["path"],
        "types": {"path": str, "formatter": str},
    },
    "generate_gcode": {
        "required": ["dxf_path", "output_path"],
        "types": {"dxf_path": str, "output_path": str, "layer": str,
                  "depth_mm": (int, float), "feed_rate": int, "safe_z": (int, float)},
    },
    # ── git ──────────────────────────────────────────────────────────────
    "git_commit": {
        "required": ["message"],
        "types": {"message": str, "repo": str, "add_all": bool},
    },
    "git_push": {
        "required": ["repo"],
        "types": {"repo": str, "remote": str, "branch": str},
    },
    "git_revert": {
        "required": ["repo", "commit"],
        "types": {"repo": str, "commit": str, "no_commit": bool},
    },
    "git_clone": {
        "required": ["url", "dest"],
        "types": {"url": str, "dest": str, "depth": int},
    },
    "git_worktree_add": {
        "required": ["repo", "path"],
        "types": {"repo": str, "path": str, "branch": str, "new_branch": str},
    },
    "git_worktree_remove": {
        "required": ["repo", "path"],
        "types": {"repo": str, "path": str, "force": bool},
    },
    # ── search / retrieval ───────────────────────────────────────────────
    "search_codebase": {
        "required": ["symbol"],
        "types": {"symbol": str, "root": str},
    },
    "vector_search": {
        "required": ["query"],
        "types": {"query": str, "collection": str, "k": int},
    },
    # ── automation / IO ──────────────────────────────────────────────────
    "send_email": {
        "required": ["to", "subject", "body"],
        "types": {"to": str, "subject": str, "body": str,
                  "smtp_host": str, "smtp_port": int, "username": str, "password": str},
    },
    "github_pr": {
        "required": ["repo_slug", "title", "head"],
        "types": {"repo_slug": str, "title": str, "head": str,
                  "base": str, "body": str, "token": str},
    },
    "calendar_add_event": {
        "required": ["path", "summary", "start"],
        "types": {"path": str, "summary": str, "start": str,
                  "end": str, "description": str},
    },
    "click_ui": {
        "required": ["x", "y"],
        "types": {"x": int, "y": int, "button": str, "clicks": int},
    },
    "type_text": {
        "required": ["text"],
        "types": {"text": str, "interval": (int, float)},
    },
    "fabrication_assist_run": {
        "required": ["objective"],
        "types": {"objective": str, "session_path": str,
                  "runner_request": str, "workspace_root": str},
    },
    # ── content creation ─────────────────────────────────────────────────
    "create_svg": {
        "required": ["path", "content"],
        "types": {"path": str, "content": str},
    },
    "create_mermaid": {
        "required": ["path", "content"],
        "types": {"path": str, "content": str},
    },
    "mcp_tools_call": {
        "required": [],
        "types": {"mcp_server": str, "tool_name": str, "arguments": dict},
    },
    "run_skill_pack": {
        "required": ["pack"],
        # payload/args are deliberately tolerant of both shapes here because the impl is too
        # (a JSON string or an object; an argv list or a bare string) — the two layers must agree.
        "types": {"pack": str, "payload": (str, dict), "args": (str, list), "timeout_seconds": int},
    },
    "notebook_edit_cell": {
        "required": ["path"],
        "types": {"path": str, "cell_index": int, "source": str},
    },
    # ── geometry / fabrication ───────────────────────────────────────────
    "geometry_execute_program": {
        "required": ["program", "workspace_root"],
        "types": {"program": (str, dict), "workspace_root": str,
                  "output_basename": str},
    },
    "gencad_generate_toolpath": {
        "required": [],
        "types": {"file": str, "strategy": str, "workspace_root": str},
    },
    # ── memory ───────────────────────────────────────────────────────────
    "ingest_chat_export_to_knowledge": {
        "required": ["export_path"],
        "types": {"export_path": str, "label": str},
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
