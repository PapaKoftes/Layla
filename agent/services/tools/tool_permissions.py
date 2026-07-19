"""Thread-local effective tool-permission context — audit S4 (tool-layer defense-in-depth).

The dispatch layer gates writes/exec *before* calling a tool, but a destructive tool executed via the
generic ``core.executor.run_tool`` path (or any future direct caller) could bypass that gate. This
records the CURRENT turn's granted permissions so the executor can fail-closed as a backstop.

Design (fail-safe, non-breaking): the context is set once per turn at the agent-loop boundary from the
request's ``allow_write`` / ``allow_run``. When NO context is active — an internal caller running
outside a turn (e.g. the config-gated ``git_auto_commit`` post-check, or the confined research-lab) —
the check is permissive so nothing existing breaks; those paths have their own gates/confinement. When
a context IS active, a destructive tool that the turn didn't grant is refused.
"""
from __future__ import annotations

import threading

_ctx = threading.local()

# Destructive tools split by the permission they require: writing/editing files (allow_write) vs
# executing code/commands/side effects (allow_run). Mirrors runtime_safety.DANGEROUS_TOOLS; a
# DANGEROUS tool absent from both sets is simply not enforced here (safe default — never a false block).
_WRITE_TOOLS = frozenset({
    "write_file", "write_files_batch", "apply_patch", "replace_in_file", "search_replace",
    "rename_symbol", "code_format", "write_csv", "create_svg", "create_mermaid",
    "notebook_edit_cell", "generate_gcode", "geometry_execute_program", "clipboard_write",
    "calendar_add_event",
})
_EXEC_TOOLS = frozenset({
    "shell", "shell_session_start", "run_python", "run_tests", "pip_install", "docker_run",
    "git_commit", "git_push", "git_revert", "git_clone", "git_worktree_add", "git_worktree_remove",
    "github_pr", "send_email", "send_webhook", "discord_send", "mcp_tools_call", "browser_click", "browser_fill",
    "run_skill_pack",
})


def set_tool_permissions(allow_write: bool, allow_run: bool) -> None:
    """Record the active turn's granted permissions (call at the turn boundary)."""
    _ctx.allow_write = bool(allow_write)
    _ctx.allow_run = bool(allow_run)
    _ctx.active = True


def clear_tool_permissions() -> None:
    """Leave the turn — subsequent internal tool calls become permissive again."""
    _ctx.active = False


def check_tool_permission(tool_name: str) -> tuple[bool, str]:
    """Return ``(ok, reason)``. Fail-closed for a destructive tool the ACTIVE turn didn't grant.
    Permissive (ok=True) when no turn context is active — internal/confined callers keep working."""
    if not getattr(_ctx, "active", False):
        return True, "no-turn-context"
    if tool_name in _WRITE_TOOLS and not getattr(_ctx, "allow_write", False):
        return False, f"'{tool_name}' needs allow_write, which is off for this turn"
    if tool_name in _EXEC_TOOLS and not getattr(_ctx, "allow_run", False):
        return False, f"'{tool_name}' needs allow_run, which is off for this turn"
    return True, "ok"
