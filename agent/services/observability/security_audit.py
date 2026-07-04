"""Security audit logging — structured records of security-sensitive events.

Records approval escalations, denied actions, protected file attempts,
dangerous tool usage, and policy bypass attempts to a dedicated ring buffer
and the standard structured logger.

All functions are fire-and-forget (never raise).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger("layla.security")

_BUFFER_SIZE = 500
_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=_BUFFER_SIZE)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _record(event_type: str, **kwargs: Any) -> None:
    """Internal: append a security event to the ring buffer and log it.

    Event fields are passed through the secret/PII redactor (BL-133/REQ-43) before being
    stored OR logged — a path/arg/token that carries a credential must not leak into the
    security log or the in-memory ring buffer. Best-effort: falls back to raw if the
    redactor is unavailable, never dropping the audit event.
    """
    entry = {
        "timestamp": _now_iso(),
        "event_type": event_type,
        **{k: v for k, v in kwargs.items() if v is not None},
    }
    try:
        from services.safety.secret_filter import redact_payload
        entry = redact_payload(entry)
    except Exception:
        pass
    with _lock:
        _events.append(entry)
    # Also emit as a structured log line
    details = " | ".join(f"{k}={v}" for k, v in sorted(entry.items()) if k != "timestamp")
    logger.info("[SECURITY] %s | %s", event_type, details)


# ── Public API ──────────────────────────────────────────────────────────


def log_approval_escalation(
    tool: str,
    *,
    reason: str = "",
    conversation_id: str = "",
    granted: bool = False,
) -> None:
    """A tool required approval escalation (human-in-the-loop gate)."""
    try:
        _record(
            "approval_escalation",
            tool=tool,
            reason=reason[:200],
            conversation_id=conversation_id,
            granted=granted,
        )
    except Exception:
        pass


def log_action_denied(
    action: str,
    *,
    reason: str = "",
    tool: str = "",
    conversation_id: str = "",
) -> None:
    """An action was denied by safety policy (planning strict, tool policy, etc.)."""
    try:
        _record(
            "action_denied",
            action=action,
            tool=tool,
            reason=reason[:200],
            conversation_id=conversation_id,
        )
    except Exception:
        pass


def log_protected_file_attempt(
    path: str,
    *,
    tool: str = "",
    conversation_id: str = "",
    blocked: bool = True,
) -> None:
    """An attempt to read/write/delete a protected file."""
    try:
        _record(
            "protected_file_attempt",
            path=path[:300],
            tool=tool,
            conversation_id=conversation_id,
            blocked=blocked,
        )
    except Exception:
        pass


def log_dangerous_tool_usage(
    tool: str,
    *,
    args_preview: str = "",
    conversation_id: str = "",
    allowed: bool = True,
) -> None:
    """A dangerous/high-privilege tool was invoked."""
    try:
        _record(
            "dangerous_tool_usage",
            tool=tool,
            args_preview=args_preview[:200],
            conversation_id=conversation_id,
            allowed=allowed,
        )
    except Exception:
        pass


def log_policy_bypass_attempt(
    policy: str,
    *,
    detail: str = "",
    conversation_id: str = "",
    blocked: bool = True,
) -> None:
    """An attempt to bypass a security policy (sandbox escape, permission override, etc.)."""
    try:
        _record(
            "policy_bypass_attempt",
            policy=policy,
            detail=detail[:200],
            conversation_id=conversation_id,
            blocked=blocked,
        )
    except Exception:
        pass


def log_sandbox_violation(
    tool: str,
    *,
    path: str = "",
    detail: str = "",
    conversation_id: str = "",
) -> None:
    """A sandbox boundary violation was detected."""
    try:
        _record(
            "sandbox_violation",
            tool=tool,
            path=path[:300],
            detail=detail[:200],
            conversation_id=conversation_id,
        )
    except Exception:
        pass


def get_recent_security_events(limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent security events (newest first)."""
    with _lock:
        events = list(_events)
    events.reverse()
    return events[:limit]


def get_security_summary() -> dict[str, Any]:
    """Return a summary of security events by type."""
    with _lock:
        events = list(_events)
    counts: dict[str, int] = {}
    for e in events:
        et = e.get("event_type", "unknown")
        counts[et] = counts.get(et, 0) + 1
    return {
        "total_events": len(events),
        "by_type": counts,
        "buffer_capacity": _BUFFER_SIZE,
    }
