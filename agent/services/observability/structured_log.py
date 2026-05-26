"""
Structured logging wrapper.

Uses structlog when available; falls back to stdlib logging.
All log calls carry run_id, aspect_id, workspace as bound context.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar

logger = logging.getLogger("layla")

# Context vars for structured logging
_log_run_id: ContextVar[str] = ContextVar("log_run_id", default="")
_log_aspect_id: ContextVar[str] = ContextVar("log_aspect_id", default="")
_log_workspace: ContextVar[str] = ContextVar("log_workspace", default="")

STRUCTLOG_AVAILABLE = False

try:
    import structlog
    STRUCTLOG_AVAILABLE = True
except ImportError:
    structlog = None


def configure_logging(json_output: bool = False) -> None:
    """Configure structured logging. Call once at startup."""
    if STRUCTLOG_AVAILABLE:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ]
        if json_output:
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        )
        logger.info("structlog configured (json=%s)", json_output)
    else:
        logger.info("structlog not available; using stdlib logging")


def bind_context(*, run_id: str = "", aspect_id: str = "", workspace: str = "") -> None:
    """Bind context variables for structured logging."""
    if run_id:
        _log_run_id.set(run_id)
    if aspect_id:
        _log_aspect_id.set(aspect_id)
    if workspace:
        _log_workspace.set(workspace)

    if STRUCTLOG_AVAILABLE:
        import structlog

        structlog.contextvars.bind_contextvars(
            run_id=run_id or _log_run_id.get(),
            aspect_id=aspect_id or _log_aspect_id.get(),
            workspace=workspace or _log_workspace.get(),
        )


def get_bound_context() -> dict:
    """Return current bound context values."""
    return {
        "run_id": _log_run_id.get(),
        "aspect_id": _log_aspect_id.get(),
        "workspace": _log_workspace.get(),
    }


def get_logger(name: str = "layla"):
    """Get a logger instance. Uses structlog when available."""
    if STRUCTLOG_AVAILABLE:
        return structlog.get_logger(name)
    return logging.getLogger(name)
