"""
Phase 4.3 — Concurrent task context isolation.
ContextVars for workspace/aspect/task_id ensure background tasks don't
mix their log lines with foreground runs. Install TaskContextFilter on
the layla logger at startup and call set_task_context() at the top of
each autonomous_run / router call.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Any

_workspace_var: ContextVar[str] = ContextVar("layla_workspace", default="")
_aspect_var: ContextVar[str] = ContextVar("layla_aspect", default="")
_task_id_var: ContextVar[str] = ContextVar("layla_task_id", default="")


# ── Public setters / getters ──────────────────────────────────────────────────

def set_task_context(
    workspace: str = "",
    aspect: str = "",
    task_id: str = "",
) -> tuple[Token, Token, Token]:
    """Set per-task context vars. Returns tokens so callers can reset on exit."""
    t_ws = _workspace_var.set(workspace or "")
    t_asp = _aspect_var.set(aspect or "")
    t_tid = _task_id_var.set(task_id or "")
    return t_ws, t_asp, t_tid


def reset_task_context(tokens: tuple[Token, Token, Token]) -> None:
    """Restore previous context vars (call in a finally block)."""
    t_ws, t_asp, t_tid = tokens
    _workspace_var.reset(t_ws)
    _aspect_var.reset(t_asp)
    _task_id_var.reset(t_tid)


def get_workspace() -> str:
    return _workspace_var.get()


def get_aspect() -> str:
    return _aspect_var.get()


def get_task_id() -> str:
    return _task_id_var.get()


def get_task_context_dict() -> dict[str, str]:
    return {
        "workspace": _workspace_var.get(),
        "aspect": _aspect_var.get(),
        "task_id": _task_id_var.get(),
    }


# ── Logging filter ────────────────────────────────────────────────────────────

class TaskContextFilter(logging.Filter):
    """Injects task_ctx attribute into log records for structured tagging."""

    def filter(self, record: logging.LogRecord) -> bool:
        ws = _workspace_var.get()
        asp = _aspect_var.get()
        tid = _task_id_var.get()
        parts: list[str] = []
        if ws:
            parts.append(f"workspace={ws}")
        if asp:
            parts.append(f"aspect={asp}")
        if tid:
            parts.append(f"task={tid}")
        record.task_ctx = f"[{', '.join(parts)}] " if parts else ""  # type: ignore[attr-defined]
        return True


def install_filter(logger_name: str = "layla") -> None:
    """Attach TaskContextFilter to the named logger (idempotent)."""
    log = logging.getLogger(logger_name)
    for f in log.filters:
        if isinstance(f, TaskContextFilter):
            return
    log.addFilter(TaskContextFilter())
