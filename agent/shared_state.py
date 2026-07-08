"""
Shared state and refs for routers. Populated by main at startup to avoid circular imports.
"""
import asyncio
import threading
from collections import deque
from typing import Callable

# Operator "steer" hints during an in-flight agent run (FIFO per conversation).
_steer_lock = threading.Lock()
_steer_hints: dict[str, deque[str]] = {}


def push_agent_steer_hint(conversation_id: str, text: str) -> None:
    """Adapter: delegates to SessionContext. Queue a short redirect for next decision tick."""
    cid = (conversation_id or "").strip() or "default"
    t = (text or "").strip()[:280]
    if not t:
        return
    try:
        from services.infrastructure.session_context import get_or_create_session
        get_or_create_session(cid).push_steer_hint(t)
    except Exception:
        # Fallback to legacy in-process store
        with _steer_lock:
            dq = _steer_hints.setdefault(cid, deque())
            dq.append(t)
            while len(dq) > 8:
                dq.popleft()


def pop_one_agent_steer_hint(conversation_id: str) -> str:
    """Adapter: delegates to SessionContext. Pop one pending steer hint (non-blocking)."""
    cid = (conversation_id or "").strip() or "default"
    try:
        from services.infrastructure.session_context import get_or_create_session
        return get_or_create_session(cid).pop_steer_hint()
    except Exception:
        pass
    with _steer_lock:
        dq = _steer_hints.get(cid)
        if not dq:
            return ""
        return dq.popleft()

# Set by main after defining _history, touch_activity, etc.
_history: deque | None = None
_conv_histories: dict[str, deque] = {}
_conv_hist_lock = threading.Lock()

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
    created = False
    with _conv_hist_lock:
        hist = _conv_histories.get(cid)
        if hist is None:
            hist = deque(maxlen=maxlen)
            _conv_histories[cid] = hist
            created = True
    if created:
        try:
            from layla.memory.conversations import get_conversation_messages

            rows = get_conversation_messages(cid, limit=maxlen)
            if rows:
                with _conv_hist_lock:
                    h = _conv_histories.get(cid)
                    if h is not None and len(h) == 0:
                        for r in rows[-int(getattr(h, "maxlen", maxlen) or maxlen):]:
                            role = (r.get("role") or "").strip()
                            content = r.get("content")
                            if role and isinstance(content, str) and content.strip():
                                h.append({"role": role, "content": content})
        except Exception:
            pass
    return hist


def append_conv_history(conversation_id: str, role: str, content: str) -> None:
    hist = get_conv_history(conversation_id)
    with _conv_hist_lock:
        hist.append({"role": role, "content": content})
    if role == "assistant":
        # Run compaction in a daemon thread — LLM summarization must never block
        # the response path (llm_serialize_lock contention otherwise stalls streaming).
        import threading as _t

        def _compact_bg(cid: str) -> None:
            try:
                import runtime_safety
                from services.context.context_manager import maybe_auto_compact

                cfg = runtime_safety.load_config()
                n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
                with _conv_hist_lock:
                    h0 = _conv_histories.get(cid)
                    snapshot = list(h0) if h0 else []
                compacted = maybe_auto_compact(snapshot, n_ctx=n_ctx, cfg=cfg)
                with _conv_hist_lock:
                    h1 = _conv_histories.get(cid)
                    if h1 is None:
                        return
                    h1.clear()
                    for item in compacted[-int(getattr(h1, "maxlen", 20) or 20):]:
                        h1.append(item)
            except Exception:
                pass

        _t.Thread(target=_compact_bg, args=((conversation_id or "").strip() or "default",), daemon=True, name="auto-compact").start()


def _cap_dict(d: dict, cap: int) -> int:
    """Drop oldest-inserted entries so len(d) <= cap. Returns count removed. Not lock-safe on its
    own — caller holds the relevant lock (or the dict is only touched here)."""
    over = len(d) - max(1, int(cap))
    if over <= 0:
        return 0
    for k in list(d.keys())[:over]:
        d.pop(k, None)
    return over


def prune_conversation_histories(max_conversations: int = 500) -> int:
    """Bound ALL the in-memory per-conversation registries (M6). Each grew one entry per distinct
    conversation for the whole process lifetime — the history deques AND the legacy trace/snapshot
    dicts (_last_coordinator_trace, _last_execution_snapshot, _last_decision_trace,
    _last_outcome_evaluation, _steer_hints, _blackboard). Durable copies live in SQLite. Drops
    oldest-inserted beyond the cap. Returns total entries removed."""
    cap = max(1, int(max_conversations))
    removed = 0
    with _conv_hist_lock:
        removed += _cap_dict(_conv_histories, cap)
    # These have their own accesses but are plain dicts; cap them best-effort under a broad guard.
    try:
        removed += _cap_dict(_last_outcome_evaluation, cap)
        removed += _cap_dict(_last_coordinator_trace, cap)
        removed += _cap_dict(_last_execution_snapshot, cap)
        removed += _cap_dict(_last_decision_trace, cap)
        removed += _cap_dict(_blackboard, cap)
        with _steer_lock:
            removed += _cap_dict(_steer_hints, cap)
    except Exception:
        pass
    return removed


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


# Last heuristic outcome evaluation per conversation (feeds next-turn planning bias).
_outcome_eval_lock = threading.Lock()
_last_outcome_evaluation: dict[str, dict] = {}


def set_last_outcome_evaluation(conversation_id: str, data: dict) -> None:
    """Adapter: delegates to SessionContext (keeps legacy in-memory cache as fallback)."""
    cid = (conversation_id or "").strip() or "default"
    if not isinstance(data, dict):
        return
    with _outcome_eval_lock:
        _last_outcome_evaluation[cid] = dict(data)
    try:
        from services.infrastructure.session_context import get_or_create_session
        get_or_create_session(cid).set_outcome_evaluation(data)
    except Exception:
        # Fallback: persist directly if session_context unavailable
        try:
            from layla.memory.db import save_outcome_evaluation
            save_outcome_evaluation(cid, data)
        except Exception:
            pass


def get_last_outcome_evaluation(conversation_id: str) -> dict | None:
    """Adapter: delegates to SessionContext (keeps legacy in-memory cache as fallback)."""
    cid = (conversation_id or "").strip() or "default"
    try:
        from services.infrastructure.session_context import get_or_create_session
        v = get_or_create_session(cid).get_outcome_evaluation()
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    # Fallback: legacy in-memory cache
    with _outcome_eval_lock:
        v = _last_outcome_evaluation.get(cid)
        if isinstance(v, dict):
            return dict(v)
    return None


def clear_last_outcome_evaluation(conversation_id: str) -> None:
    cid = (conversation_id or "").strip() or "default"
    with _outcome_eval_lock:
        _last_outcome_evaluation.pop(cid, None)
    try:
        from services.infrastructure.session_context import get_or_create_session
        get_or_create_session(cid).clear_outcome_evaluation()
    except Exception:
        pass


# Coordinator classification trace (last run per conversation; UI / debug)
_coordinator_trace_lock = threading.Lock()
_last_coordinator_trace: dict[str, dict] = {}


def set_last_coordinator_trace(conversation_id: str, data: dict) -> None:
    """Adapter: delegates to SessionContext."""
    cid = (conversation_id or "").strip() or "default"
    if not isinstance(data, dict):
        return
    with _coordinator_trace_lock:
        _last_coordinator_trace[cid] = dict(data)
    try:
        from services.infrastructure.session_context import get_or_create_session
        get_or_create_session(cid).set_coordinator_trace(data)
    except Exception:
        pass


def get_last_coordinator_trace(conversation_id: str) -> dict | None:
    """Adapter: delegates to SessionContext."""
    cid = (conversation_id or "").strip() or "default"
    try:
        from services.infrastructure.session_context import get_or_create_session
        v = get_or_create_session(cid).get_coordinator_trace()
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    with _coordinator_trace_lock:
        v = _last_coordinator_trace.get(cid)
        return dict(v) if isinstance(v, dict) else None


def clear_last_coordinator_trace(conversation_id: str) -> None:
    cid = (conversation_id or "").strip() or "default"
    with _coordinator_trace_lock:
        _last_coordinator_trace.pop(cid, None)
    try:
        from services.infrastructure.session_context import get_or_create_session
        get_or_create_session(cid).clear_coordinator_trace()
    except Exception:
        pass


# Last execution snapshot per conversation (debug / UI trace panel)
_execution_snap_lock = threading.Lock()
_last_execution_snapshot: dict[str, dict] = {}


def set_last_execution_snapshot(conversation_id: str, data: dict) -> None:
    """Adapter: delegates to SessionContext."""
    cid = (conversation_id or "").strip() or "default"
    if not isinstance(data, dict):
        return
    with _execution_snap_lock:
        _last_execution_snapshot[cid] = dict(data)
    try:
        from services.infrastructure.session_context import get_or_create_session
        get_or_create_session(cid).set_execution_snapshot(data)
    except Exception:
        pass


def get_last_execution_snapshot(conversation_id: str) -> dict | None:
    """Adapter: delegates to SessionContext."""
    cid = (conversation_id or "").strip() or "default"
    try:
        from services.infrastructure.session_context import get_or_create_session
        v = get_or_create_session(cid).get_execution_snapshot()
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    with _execution_snap_lock:
        v = _last_execution_snapshot.get(cid)
        return dict(v) if isinstance(v, dict) else None


def clear_last_execution_snapshot(conversation_id: str) -> None:
    cid = (conversation_id or "").strip() or "default"
    with _execution_snap_lock:
        _last_execution_snapshot.pop(cid, None)
    try:
        from services.infrastructure.session_context import get_or_create_session
        get_or_create_session(cid).clear_execution_snapshot()
    except Exception:
        pass


# Last decision policy trace per conversation (for /agent/decision_trace)
_decision_trace_lock = threading.Lock()
_last_decision_trace: dict[str, list] = {}


def set_last_decision_trace(conversation_id: str, traces: list) -> None:
    cid = (conversation_id or "").strip() or "default"
    if not isinstance(traces, list):
        return
    with _decision_trace_lock:
        _last_decision_trace[cid] = list(traces)


def get_last_decision_trace(conversation_id: str) -> list | None:
    cid = (conversation_id or "").strip() or "default"
    with _decision_trace_lock:
        v = _last_decision_trace.get(cid)
        return list(v) if isinstance(v, list) else None


# Namespaced blackboard for spawned agents / jobs (thread-safe, in-process)
_bb_lock = threading.Lock()
_blackboard: dict[str, dict[str, object]] = {}


def blackboard_put(job_id: str, key: str, value: object, holder: str = "") -> None:
    jid = (job_id or "").strip() or "default"
    k = (key or "").strip()[:200]
    if not k:
        return
    with _bb_lock:
        slot = _blackboard.setdefault(jid, {"_holder": "", "_updated": 0.0})
        slot[k] = value
        if holder:
            slot["_holder"] = holder[:120]


def blackboard_get(job_id: str) -> dict[str, object]:
    jid = (job_id or "").strip() or "default"
    with _bb_lock:
        raw = _blackboard.get(jid)
        return dict(raw) if isinstance(raw, dict) else {}


def blackboard_clear(job_id: str) -> None:
    jid = (job_id or "").strip() or "default"
    with _bb_lock:
        _blackboard.pop(jid, None)


_workspace_lease_lock = threading.Lock()
_workspace_lease: dict[str, tuple[str, float]] = {}


def try_acquire_workspace_lease(workspace: str, holder: str, ttl_seconds: float = 3600.0) -> bool:
    """Single-writer hint per workspace path (best-effort, in-process)."""
    import time as _time

    ws = (workspace or "").strip()
    h = (holder or "").strip()[:120]
    if not ws or not h:
        return False
    now = _time.monotonic()
    ttl = max(30.0, float(ttl_seconds))
    with _workspace_lease_lock:
        cur = _workspace_lease.get(ws)
        if cur is None or cur[1] < now:
            _workspace_lease[ws] = (h, now + ttl)
            return True
        return cur[0] == h


def release_workspace_lease(workspace: str, holder: str) -> None:
    ws = (workspace or "").strip()
    h = (holder or "").strip()[:120]
    with _workspace_lease_lock:
        cur = _workspace_lease.get(ws)
        if cur and cur[0] == h:
            _workspace_lease.pop(ws, None)


# ── Cancellation support (merged from PR #1) ─────────────────────────────────
_cancel_events: dict[str, asyncio.Event] = {}
_most_recent_conv_id: str | None = None
_cancel_lock = threading.Lock()


def new_cancel_event(conv_id: str) -> asyncio.Event:
    """Create (or reset) a cancel event for conv_id. Call at start of each run."""
    global _most_recent_conv_id
    ev = asyncio.Event()
    with _cancel_lock:
        _cancel_events[conv_id] = ev
        _most_recent_conv_id = conv_id
    return ev


def get_cancel_event(conv_id: str) -> asyncio.Event | None:
    """Return the cancel event for conv_id, or None if not found."""
    with _cancel_lock:
        return _cancel_events.get(conv_id)


def set_cancel(conv_id: str) -> bool:
    """Signal cancellation for conv_id. Returns True if event existed."""
    with _cancel_lock:
        ev = _cancel_events.get(conv_id)
    if ev is not None:
        ev.set()
        return True
    return False


def clear_cancel(conv_id: str) -> None:
    """Remove cancel event for conv_id (call after run completes)."""
    with _cancel_lock:
        _cancel_events.pop(conv_id, None)


def get_most_recent_conv_id() -> str | None:
    """Return the most recently started conversation_id."""
    with _cancel_lock:
        return _most_recent_conv_id


# Shared pending-file lock: agent_loop pending writes vs main router reads
pending_file_lock: threading.Lock = threading.Lock()
