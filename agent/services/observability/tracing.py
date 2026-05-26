"""
Request tracing with correlation IDs.

Provides per-request correlation context using contextvars so that every log
line emitted during a single request/agent-iteration can be tied together.
Pure stdlib -- no external dependencies.
"""
from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger("layla.observability.tracing")

# ---------------------------------------------------------------------------
# Correlation ID helpers
# ---------------------------------------------------------------------------

_correlation_id_var: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)


def generate_correlation_id() -> str:
    """Return a new random correlation ID (uuid4 hex, 32 chars)."""
    return uuid.uuid4().hex


def get_current_correlation_id() -> Optional[str]:
    """Return the correlation ID bound to the current async/thread context."""
    return _correlation_id_var.get()


class CorrelationContext:
    """Context manager that binds a correlation ID for the current context.

    Usage::

        with CorrelationContext(cid):
            # everything inside sees *cid* via get_current_correlation_id()
            ...

    The previous value is restored when the block exits.
    """

    def __init__(self, correlation_id: Optional[str] = None) -> None:
        self.correlation_id = correlation_id or generate_correlation_id()
        self._token: object = None  # contextvars.Token

    def __enter__(self) -> "CorrelationContext":
        self._token = _correlation_id_var.set(self.correlation_id)
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self._token is not None:
            _correlation_id_var.reset(self._token)


# ---------------------------------------------------------------------------
# Structured trace logging
# ---------------------------------------------------------------------------


def trace_request(
    correlation_id: str,
    method: str,
    path: str,
    duration_ms: float,
    status_code: int,
) -> None:
    """Emit a structured JSON log line for a completed request.

    Parameters
    ----------
    correlation_id:
        The correlation ID that ties this request to related log entries.
    method:
        HTTP method (GET, POST, ...).
    path:
        Request path (e.g. ``/api/chat``).
    duration_ms:
        Wall-clock duration of the request in milliseconds.
    status_code:
        HTTP response status code.
    """
    entry = {
        "event": "request_trace",
        "correlation_id": correlation_id,
        "method": method,
        "path": path,
        "duration_ms": round(duration_ms, 2),
        "status_code": status_code,
    }
    logger.info(json.dumps(entry, separators=(",", ":")))
