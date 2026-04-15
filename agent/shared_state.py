"""
Shared state and refs for routers. Populated by main at startup to avoid circular imports.
"""
import threading
from collections import deque
from typing import Callable

# Operator "steer" hints during an in-flight agent run (FIFO per conversation).
_steer_lock = threading.Lock()
_steer_hints: dict[str, deque[str]] = {}


def push_agent_steer_hint(conversation_id: str, text: str) -> None:
    """Queue a short redirect for the next decision tick of this conversation's run."""
    cid = (conversation_id or "").strip() or "default"
    t = (text or "").strip()[:280]
    if not t:
        return
    with _steer_lock:
        dq = _steer_hints.setdefault(cid, deque())
        dq.append(t)
        while len(dq) > 8:
            dq.popleft()


def pop_one_agent_steer_hint(conversation_id: str) -> str:
    """Pop one pending steer hint (non-blocking)."""
    cid = (conversation_id or "").strip() or "default"
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
                from services.context_manager import maybe_auto_compact

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
    cid = (conversation_id or "").strip() or "default"
    if not isinstance(data, dict):
        return
    with _outcome_eval_lock:
        _last_outcome_evaluation[cid] = dict(data)
    try:
        from layla.memory.db import save_outcome_evaluation

        save_outcome_evaluation(cid, data)
    except Exception:
        pass


def get_last_outcome_evaluation(conversation_id: str) -> dict | None:
    cid = (conversation_id or "").strip() or "default"
    with _outcome_eval_lock:
        v = _last_outcome_evaluation.get(cid)
        if isinstance(v, dict):
            return dict(v)
    try:
        from layla.memory.db import get_last_outcome_evaluation_record

        v2 = get_last_outcome_evaluation_record(cid)
        if isinstance(v2, dict):
            with _outcome_eval_lock:
                _last_outcome_evaluation[cid] = dict(v2)
            return dict(v2)
    except Exception:
        pass
    return None


def clear_last_outcome_evaluation(conversation_id: str) -> None:
    cid = (conversation_id or "").strip() or "default"
    with _outcome_eval_lock:
        _last_outcome_evaluation.pop(cid, None)


# Coordinator classification trace (last run per conversation; UI / debug)
_coordinator_trace_lock = threading.Lock()
_last_coordinator_trace: dict[str, dict] = {}


def set_last_coordinator_trace(conversation_id: str, data: dict) -> None:
    cid = (conversation_id or "").strip() or "default"
    if not isinstance(data, dict):
        return
    with _coordinator_trace_lock:
        _last_coordinator_trace[cid] = dict(data)


def get_last_coordinator_trace(conversation_id: str) -> dict | None:
    cid = (conversation_id or "").strip() or "default"
    with _coordinator_trace_lock:
        v = _last_coordinator_trace.get(cid)
        return dict(v) if isinstance(v, dict) else None


def clear_last_coordinator_trace(conversation_id: str) -> None:
    cid = (conversation_id or "").strip() or "default"
    with _coordinator_trace_lock:
        _last_coordinator_trace.pop(cid, None)


# Last execution snapshot per conversation (debug / UI trace panel)
_execution_snap_lock = threading.Lock()
_last_execution_snapshot: dict[str, dict] = {}


def set_last_execution_snapshot(conversation_id: str, data: dict) -> None:
    cid = (conversation_id or "").strip() or "default"
    if not isinstance(data, dict):
        return
    with _execution_snap_lock:
        _last_execution_snapshot[cid] = dict(data)


def get_last_execution_snapshot(conversation_id: str) -> dict | None:
    cid = (conversation_id or "").strip() or "default"
    with _execution_snap_lock:
        v = _last_execution_snapshot.get(cid)
        return dict(v) if isinstance(v, dict) else None


def clear_last_execution_snapshot(conversation_id: str) -> None:
    cid = (conversation_id or "").strip() or "default"
    with _execution_snap_lock:
        _last_execution_snapshot.pop(cid, None)


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
