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
    if role == "assistant":
        # Run compaction in a daemon thread — LLM summarization must never block
        # the response path (llm_serialize_lock contention otherwise stalls streaming).
        import threading as _t

        def _compact_bg(h: list) -> None:
            try:
                import runtime_safety
                from services.context_manager import maybe_auto_compact

                cfg = runtime_safety.load_config()
                n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
                compacted = maybe_auto_compact(h, n_ctx=n_ctx, cfg=cfg)
                h[:] = compacted
            except Exception:
                pass

        _t.Thread(target=_compact_bg, args=(hist,), daemon=True, name="auto-compact").start()


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
