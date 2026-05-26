"""
Structured event logging with an in-memory ring buffer.

Every event carries a timestamp, event type, optional correlation ID, and an
arbitrary data dict.  Recent events are kept in a bounded deque so that
dashboards / health endpoints can inspect them without touching disk.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from threading import Lock
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger("layla.observability.events")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EventType = Literal[
    "tool_execution",
    "agent_iteration",
    "memory_operation",
    "llm_completion",
    "error",
]

_VALID_EVENT_TYPES: frozenset[str] = frozenset(EventType.__args__)  # type: ignore[attr-defined]
_BUFFER_MAXLEN = 500

# ---------------------------------------------------------------------------
# Ring buffer (module-level, thread-safe)
# ---------------------------------------------------------------------------

_lock = Lock()
_events: deque[Dict[str, Any]] = deque(maxlen=_BUFFER_MAXLEN)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_event(
    event_type: str,
    data: Dict[str, Any],
    correlation_id: Optional[str] = None,
    level: str = "info",
) -> Dict[str, Any]:
    """Record a structured event and return the event dict.

    Parameters
    ----------
    event_type:
        One of the recognised ``EventType`` literals.  Unknown types are
        still accepted (logged at WARNING) for forward-compatibility.
    data:
        Arbitrary payload associated with the event.
    correlation_id:
        Optional request / iteration correlation ID.
    level:
        Python log level name (``"debug"``, ``"info"``, ``"warning"``,
        ``"error"``).  Defaults to ``"info"``.
    """
    if event_type not in _VALID_EVENT_TYPES:
        logger.warning("Unknown event_type %r -- recording anyway", event_type)

    entry: Dict[str, Any] = {
        "timestamp": time.time(),
        "event_type": event_type,
        "correlation_id": correlation_id,
        "data": data,
    }

    with _lock:
        _events.append(entry)

    # Also emit via stdlib logging so file/stream handlers can capture it.
    log_fn = getattr(logger, level, logger.info)
    log_fn(json.dumps(entry, default=str, separators=(",", ":")))

    return entry


def get_recent_events(
    event_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return up to *limit* recent events, newest first.

    Parameters
    ----------
    event_type:
        If given, only events matching this type are returned.
    limit:
        Maximum number of events to return.  Defaults to 50.
    """
    with _lock:
        snapshot = list(_events)
    # newest first
    snapshot.reverse()
    if event_type is not None:
        snapshot = [e for e in snapshot if e["event_type"] == event_type]
    return snapshot[:limit]
