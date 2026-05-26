"""Session-scoped state container (Phase 3, Section 5.2 of remediation plan).

SessionContext replaces scattered shared_state globals with a per-conversation
scoped object.  It holds all mutable state for a single agent run:

  - steer hints
  - outcome evaluation
  - coordinator trace
  - execution snapshot
  - decision trace
  - blackboard (key-value scratch space)
  - workspace leases
  - cancellation events

Usage:
    # In routers / lifespan:
    ctx = get_or_create_session("conv-123")
    ctx.push_steer_hint("focus on tests")
    hint = ctx.pop_steer_hint()

    # Dependency-injection style (FastAPI):
    from fastapi import Depends
    def get_session(request: Request) -> SessionContext:
        cid = request.headers.get("x-conversation-id", "default")
        return get_or_create_session(cid)

Migration path:
  1. Create SessionContext alongside shared_state.py (this file)
  2. Add adapter functions that delegate from shared_state → SessionContext
  3. Migrate callers one-at-a-time to use SessionContext directly
  4. Eventually deprecate shared_state.py
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class SessionContext:
    """Per-conversation session state.

    Thread-safe via a single reentrant lock per session. All methods
    that mutate state acquire the lock.
    """

    __slots__ = (
        "conversation_id",
        "_lock",
        "_steer_hints",
        "_outcome_evaluation",
        "_coordinator_trace",
        "_execution_snapshot",
        "_decision_trace",
        "_blackboard",
        "_workspace_leases",
        "_cancel_event",
        "_created_at",
    )

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._lock = threading.RLock()
        self._steer_hints: deque[str] = deque(maxlen=8)
        self._outcome_evaluation: dict | None = None
        self._coordinator_trace: dict | None = None
        self._execution_snapshot: dict | None = None
        self._decision_trace: dict | None = None
        self._blackboard: dict[str, Any] = {}
        self._workspace_leases: dict[str, tuple[str, float]] = {}  # path -> (holder, expires)
        self._cancel_event: threading.Event | None = None
        self._created_at = time.monotonic()

    # ── Steer hints ──────────────────────────────────────────────────────

    def push_steer_hint(self, text: str) -> None:
        t = (text or "").strip()[:280]
        if not t:
            return
        with self._lock:
            self._steer_hints.append(t)

    def pop_steer_hint(self) -> str:
        with self._lock:
            if not self._steer_hints:
                return ""
            return self._steer_hints.popleft()

    # ── Outcome evaluation ───────────────────────────────────────────────

    def set_outcome_evaluation(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._outcome_evaluation = dict(data)
        # Persist to DB (fire-and-forget)
        try:
            from layla.memory.db import save_outcome_evaluation
            save_outcome_evaluation(self.conversation_id, data)
        except Exception:
            pass

    def get_outcome_evaluation(self) -> dict | None:
        with self._lock:
            v = self._outcome_evaluation
            if isinstance(v, dict):
                return dict(v)
        # Fallback: check DB
        try:
            from layla.memory.db import get_last_outcome_evaluation_record
            v2 = get_last_outcome_evaluation_record(self.conversation_id)
            if isinstance(v2, dict):
                with self._lock:
                    self._outcome_evaluation = dict(v2)
                return dict(v2)
        except Exception:
            pass
        return None

    def clear_outcome_evaluation(self) -> None:
        with self._lock:
            self._outcome_evaluation = None

    # ── Coordinator trace ────────────────────────────────────────────────

    def set_coordinator_trace(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._coordinator_trace = dict(data)

    def get_coordinator_trace(self) -> dict | None:
        with self._lock:
            v = self._coordinator_trace
            return dict(v) if isinstance(v, dict) else None

    def clear_coordinator_trace(self) -> None:
        with self._lock:
            self._coordinator_trace = None

    # ── Execution snapshot ───────────────────────────────────────────────

    def set_execution_snapshot(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._execution_snapshot = dict(data)

    def get_execution_snapshot(self) -> dict | None:
        with self._lock:
            v = self._execution_snapshot
            return dict(v) if isinstance(v, dict) else None

    def clear_execution_snapshot(self) -> None:
        with self._lock:
            self._execution_snapshot = None

    # ── Decision trace ───────────────────────────────────────────────────

    def set_decision_trace(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._decision_trace = dict(data)

    def get_decision_trace(self) -> dict | None:
        with self._lock:
            v = self._decision_trace
            return dict(v) if isinstance(v, dict) else None

    # ── Blackboard ───────────────────────────────────────────────────────

    def blackboard_put(self, key: str, value: Any, *, ttl: float = 0) -> None:
        with self._lock:
            expires = time.monotonic() + ttl if ttl > 0 else 0
            self._blackboard[key] = (value, expires)

    def blackboard_get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._blackboard.get(key)
            if entry is None:
                return default
            value, expires = entry
            if expires > 0 and time.monotonic() > expires:
                del self._blackboard[key]
                return default
            return value

    def blackboard_clear(self) -> None:
        with self._lock:
            self._blackboard.clear()

    # ── Workspace leases ─────────────────────────────────────────────────

    def try_acquire_workspace_lease(
        self, path: str, holder: str, ttl_seconds: float = 600,
    ) -> bool:
        with self._lock:
            now = time.monotonic()
            existing = self._workspace_leases.get(path)
            if existing:
                ex_holder, ex_expires = existing
                if ex_expires > now and ex_holder != holder:
                    return False
            self._workspace_leases[path] = (holder, now + ttl_seconds)
            return True

    def release_workspace_lease(self, path: str, holder: str) -> bool:
        with self._lock:
            existing = self._workspace_leases.get(path)
            if existing and existing[0] == holder:
                del self._workspace_leases[path]
                return True
            return False

    # ── Cancellation ─────────────────────────────────────────────────────

    def new_cancel_event(self) -> threading.Event:
        with self._lock:
            self._cancel_event = threading.Event()
            return self._cancel_event

    def get_cancel_event(self) -> threading.Event | None:
        return self._cancel_event

    def set_cancel(self) -> None:
        with self._lock:
            if self._cancel_event is not None:
                self._cancel_event.set()

    def clear_cancel(self) -> None:
        with self._lock:
            self._cancel_event = None


# ── Session registry ─────────────────────────────────────────────────────

_sessions_lock = threading.Lock()
_sessions: dict[str, SessionContext] = {}


def get_or_create_session(conversation_id: str) -> SessionContext:
    """Get or lazily create a SessionContext for the given conversation ID."""
    cid = (conversation_id or "").strip() or "default"
    with _sessions_lock:
        ctx = _sessions.get(cid)
        if ctx is None:
            ctx = SessionContext(cid)
            _sessions[cid] = ctx
        return ctx


def get_session(conversation_id: str) -> SessionContext | None:
    """Get an existing SessionContext without creating one."""
    cid = (conversation_id or "").strip() or "default"
    with _sessions_lock:
        return _sessions.get(cid)


def remove_session(conversation_id: str) -> None:
    """Remove a session when the conversation ends."""
    cid = (conversation_id or "").strip() or "default"
    with _sessions_lock:
        _sessions.pop(cid, None)


def list_sessions() -> list[str]:
    """Return all active session conversation IDs."""
    with _sessions_lock:
        return list(_sessions.keys())


def prune_stale_sessions(max_age_seconds: float = 3600) -> int:
    """Remove sessions older than *max_age_seconds*. Returns count removed."""
    now = time.monotonic()
    to_remove: list[str] = []
    with _sessions_lock:
        for cid, ctx in _sessions.items():
            if now - ctx._created_at > max_age_seconds:
                to_remove.append(cid)
        for cid in to_remove:
            _sessions.pop(cid, None)
    return len(to_remove)


def session_count() -> int:
    """Return the number of active sessions."""
    with _sessions_lock:
        return len(_sessions)
