"""Tests for services.session_context — per-conversation scoped state."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.infrastructure.session_context import (
    SessionContext,
    get_or_create_session,
    get_session,
    list_sessions,
    remove_session,
)


# ── Steer hints ──────────────────────────────────────────────────────────


def test_push_pop_steer_hint():
    ctx = SessionContext("test-1")
    ctx.push_steer_hint("focus on tests")
    assert ctx.pop_steer_hint() == "focus on tests"
    assert ctx.pop_steer_hint() == ""  # empty after pop


def test_steer_hints_fifo():
    ctx = SessionContext("test-2")
    ctx.push_steer_hint("a")
    ctx.push_steer_hint("b")
    ctx.push_steer_hint("c")
    assert ctx.pop_steer_hint() == "a"
    assert ctx.pop_steer_hint() == "b"
    assert ctx.pop_steer_hint() == "c"


def test_steer_hints_overflow():
    ctx = SessionContext("test-3")
    for i in range(12):
        ctx.push_steer_hint(f"hint-{i}")
    # Maxlen is 8, oldest should be dropped
    hints = []
    while True:
        h = ctx.pop_steer_hint()
        if not h:
            break
        hints.append(h)
    assert len(hints) == 8
    assert hints[0] == "hint-4"  # oldest surviving


def test_steer_hint_empty_ignored():
    ctx = SessionContext("test-4")
    ctx.push_steer_hint("")
    ctx.push_steer_hint("   ")
    assert ctx.pop_steer_hint() == ""


# ── Outcome evaluation ───────────────────────────────────────────────────


def test_outcome_evaluation_lifecycle():
    ctx = SessionContext("test-5")
    assert ctx.get_outcome_evaluation() is None
    ctx.set_outcome_evaluation({"score": 0.8, "success": True})
    result = ctx.get_outcome_evaluation()
    assert result["score"] == 0.8
    # Returns a copy, not the same object
    result["score"] = 0.0
    assert ctx.get_outcome_evaluation()["score"] == 0.8
    ctx.clear_outcome_evaluation()
    assert ctx.get_outcome_evaluation() is None


def test_outcome_evaluation_rejects_non_dict():
    ctx = SessionContext("test-6")
    ctx.set_outcome_evaluation("not a dict")  # type: ignore
    assert ctx.get_outcome_evaluation() is None


# ── Coordinator trace ────────────────────────────────────────────────────


def test_coordinator_trace_lifecycle():
    ctx = SessionContext("test-7")
    assert ctx.get_coordinator_trace() is None
    ctx.set_coordinator_trace({"step": 1})
    assert ctx.get_coordinator_trace()["step"] == 1
    ctx.clear_coordinator_trace()
    assert ctx.get_coordinator_trace() is None


# ── Execution snapshot ───────────────────────────────────────────────────


def test_execution_snapshot_lifecycle():
    ctx = SessionContext("test-8")
    assert ctx.get_execution_snapshot() is None
    ctx.set_execution_snapshot({"tools_used": ["read_file"]})
    snap = ctx.get_execution_snapshot()
    assert snap["tools_used"] == ["read_file"]
    ctx.clear_execution_snapshot()
    assert ctx.get_execution_snapshot() is None


# ── Decision trace ───────────────────────────────────────────────────────


def test_decision_trace_lifecycle():
    ctx = SessionContext("test-9")
    assert ctx.get_decision_trace() is None
    ctx.set_decision_trace({"action": "tool", "tool": "read_file"})
    trace = ctx.get_decision_trace()
    assert trace["action"] == "tool"


# ── Blackboard ───────────────────────────────────────────────────────────


def test_blackboard_put_get():
    ctx = SessionContext("test-10")
    ctx.blackboard_put("key1", "value1")
    assert ctx.blackboard_get("key1") == "value1"
    assert ctx.blackboard_get("missing", "default") == "default"


def test_blackboard_ttl():
    ctx = SessionContext("test-11")
    ctx.blackboard_put("ephemeral", 42, ttl=0.01)  # 10ms TTL
    assert ctx.blackboard_get("ephemeral") == 42
    time.sleep(0.02)
    assert ctx.blackboard_get("ephemeral") is None


def test_blackboard_clear():
    ctx = SessionContext("test-12")
    ctx.blackboard_put("a", 1)
    ctx.blackboard_put("b", 2)
    ctx.blackboard_clear()
    assert ctx.blackboard_get("a") is None
    assert ctx.blackboard_get("b") is None


# ── Workspace leases ─────────────────────────────────────────────────────


def test_workspace_lease_acquire_release():
    ctx = SessionContext("test-13")
    assert ctx.try_acquire_workspace_lease("/tmp/ws", "agent-1")
    assert ctx.release_workspace_lease("/tmp/ws", "agent-1")


def test_workspace_lease_conflict():
    ctx = SessionContext("test-14")
    assert ctx.try_acquire_workspace_lease("/tmp/ws", "agent-1")
    # Different holder can't acquire
    assert not ctx.try_acquire_workspace_lease("/tmp/ws", "agent-2")
    # Same holder can re-acquire
    assert ctx.try_acquire_workspace_lease("/tmp/ws", "agent-1")


def test_workspace_lease_wrong_holder_release():
    ctx = SessionContext("test-15")
    ctx.try_acquire_workspace_lease("/tmp/ws", "agent-1")
    assert not ctx.release_workspace_lease("/tmp/ws", "agent-2")


def test_workspace_lease_expired():
    ctx = SessionContext("test-16")
    ctx.try_acquire_workspace_lease("/tmp/ws", "agent-1", ttl_seconds=0.01)
    time.sleep(0.02)
    # Expired lease can be taken by another holder
    assert ctx.try_acquire_workspace_lease("/tmp/ws", "agent-2")


# ── Cancellation ─────────────────────────────────────────────────────────


def test_cancel_event_lifecycle():
    ctx = SessionContext("test-17")
    assert ctx.get_cancel_event() is None
    ev = ctx.new_cancel_event()
    assert not ev.is_set()
    ctx.set_cancel()
    assert ev.is_set()
    ctx.clear_cancel()
    assert ctx.get_cancel_event() is None


# ── Session registry ─────────────────────────────────────────────────────


def test_get_or_create_session():
    ctx1 = get_or_create_session("reg-1")
    ctx2 = get_or_create_session("reg-1")
    assert ctx1 is ctx2  # same object


def test_get_session_returns_none():
    assert get_session("nonexistent-session-xyz") is None


def test_remove_session():
    get_or_create_session("reg-2")
    remove_session("reg-2")
    assert get_session("reg-2") is None


def test_list_sessions():
    get_or_create_session("list-1")
    get_or_create_session("list-2")
    sessions = list_sessions()
    assert "list-1" in sessions
    assert "list-2" in sessions


# ── Thread safety ────────────────────────────────────────────────────────


def test_concurrent_steer_hints():
    ctx = SessionContext("thread-1")
    errors = []

    def pusher(n):
        try:
            for i in range(50):
                ctx.push_steer_hint(f"thread-{n}-{i}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=pusher, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors


def test_concurrent_blackboard():
    ctx = SessionContext("thread-2")
    errors = []

    def writer(n):
        try:
            for i in range(50):
                ctx.blackboard_put(f"key-{n}-{i}", i)
                ctx.blackboard_get(f"key-{n}-{i}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors


# ── Session count & pruning ─────────────────────────────────────────────


def test_session_count():
    from services.infrastructure.session_context import session_count, _sessions, _sessions_lock

    with _sessions_lock:
        before = len(_sessions)
    get_or_create_session("count-test-1")
    get_or_create_session("count-test-2")
    assert session_count() >= before + 2


def test_prune_stale_sessions():
    from services.infrastructure.session_context import prune_stale_sessions, _sessions, _sessions_lock

    # Create a session with artificially old _created_at
    ctx = get_or_create_session("prune-old")
    ctx._created_at = time.monotonic() - 7200  # 2 hours ago

    removed = prune_stale_sessions(max_age_seconds=3600)
    assert removed >= 1
    assert get_session("prune-old") is None


def test_prune_keeps_fresh_sessions():
    from services.infrastructure.session_context import prune_stale_sessions

    ctx = get_or_create_session("prune-fresh")
    # _created_at is just now, so it should survive pruning
    prune_stale_sessions(max_age_seconds=3600)
    assert get_session("prune-fresh") is not None
