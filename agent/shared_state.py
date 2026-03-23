"""
Shared state and refs for routers. Populated by main at startup to avoid circular imports.
"""
import asyncio
from collections import deque
from typing import Callable

# Set by main after defining _history, touch_activity, etc.
_history: deque | None = None
_conv_histories: dict[str, deque] = {}

# Last Layla auto-commit: for /undo
_last_layla_commit_repo: str | None = None
_last_layla_commit_hash: str | None = None
_touch_activity: Callable[[], None] | None = None
_read_pending: Callable[[], list] | None = None
_write_pending_list: Callable[[list], None] | None = None
_audit_fn: Callable[[str, str, str, bool], None] | None = None
_append_history: Callable[[str, str], None] | None = None
_run_autonomous_study: Callable | None = None


def set_refs(
    history: deque,
    touch_activity: Callable[[], None],
    read_pending: Callable[[], list],
    write_pending_list: Callable[[list], None],
    audit_fn: Callable[[str, str, str, bool], None],
    append_history: Callable[[str, str], None],
    run_autonomous_study: Callable | None = None,
) -> None:
    global _history, _touch_activity, _read_pending, _write_pending_list, _audit_fn, _append_history, _run_autonomous_study
    _history = history
    _touch_activity = touch_activity
    _read_pending = read_pending
    _write_pending_list = write_pending_list
    _audit_fn = audit_fn
    _append_history = append_history
    _run_autonomous_study = run_autonomous_study


def get_history() -> deque:
    if _history is None:
        raise RuntimeError("shared_state not initialized")
    return _history


def get_conv_history(conversation_id: str, maxlen: int = 20) -> deque:
    cid = (conversation_id or "").strip() or "default"
    hist = _conv_histories.get(cid)
    if hist is None:
        hist = deque(maxlen=maxlen)
        _conv_histories[cid] = hist
    return hist


def append_conv_history(conversation_id: str, role: str, content: str) -> None:
    hist = get_conv_history(conversation_id)
    hist.append({"role": role, "content": content})


def get_touch_activity() -> Callable[[], None]:
    if _touch_activity is None:
        raise RuntimeError("shared_state not initialized")
    return _touch_activity


def get_read_pending() -> Callable[[], list]:
    if _read_pending is None:
        raise RuntimeError("shared_state not initialized")
    return _read_pending


def get_write_pending_list() -> Callable[[list], None]:
    if _write_pending_list is None:
        raise RuntimeError("shared_state not initialized")
    return _write_pending_list


def get_audit() -> Callable[[str, str, str, bool], None]:
    if _audit_fn is None:
        raise RuntimeError("shared_state not initialized")
    return _audit_fn


def get_append_history() -> Callable[[str, str], None]:
    if _append_history is None:
        raise RuntimeError("shared_state not initialized")
    return _append_history


def get_run_autonomous_study() -> Callable | None:
    return _run_autonomous_study


def set_last_layla_commit(repo: str, commit_hash: str) -> None:
    global _last_layla_commit_repo, _last_layla_commit_hash
    _last_layla_commit_repo = repo
    _last_layla_commit_hash = commit_hash


def get_last_layla_commit() -> tuple[str | None, str | None]:
    return _last_layla_commit_repo, _last_layla_commit_hash


# ── Cancellation support ──────────────────────────────────────────────────────
# Maps conversation_id -> asyncio.Event. Set the event to request cancellation.
_cancel_events: dict[str, asyncio.Event] = {}
# Track the most-recently started conversation_id for DELETE /agent
_most_recent_conv_id: str | None = None


def new_cancel_event(conv_id: str) -> asyncio.Event:
    """Create (or reset) a cancel event for conv_id. Call at start of each run."""
    global _most_recent_conv_id
    ev = asyncio.Event()
    _cancel_events[conv_id] = ev
    _most_recent_conv_id = conv_id
    return ev


def get_cancel_event(conv_id: str) -> asyncio.Event | None:
    """Return the cancel event for conv_id, or None if not found."""
    return _cancel_events.get(conv_id)


def set_cancel(conv_id: str) -> bool:
    """Signal cancellation for conv_id. Returns True if event existed."""
    ev = _cancel_events.get(conv_id)
    if ev is not None:
        ev.set()
        return True
    return False


def clear_cancel(conv_id: str) -> None:
    """Remove cancel event for conv_id (call after run completes)."""
    _cancel_events.pop(conv_id, None)


def get_most_recent_conv_id() -> str | None:
    """Return the most recently started conversation_id."""
    return _most_recent_conv_id
