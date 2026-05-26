"""Tests for services.observability.security_audit ring-buffer audit log."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_ring_buffer():
    """Reset the module-level ring buffer before and after each test."""
    from services.observability import security_audit as sa

    sa._events.clear()
    yield
    sa._events.clear()


# ── 1. log_approval_escalation ────────────────────────────────────────────────

def test_log_approval_escalation():
    from services.observability import security_audit as sa

    sa.log_approval_escalation("shell_exec", reason="needs sudo", granted=True)
    events = sa.get_recent_security_events(limit=10)

    assert len(events) == 1
    evt = events[0]
    assert evt["event_type"] == "approval_escalation"
    assert evt["tool"] == "shell_exec"
    assert evt["reason"] == "needs sudo"
    assert evt["granted"] is True


# ── 2. log_action_denied ─────────────────────────────────────────────────────

def test_log_action_denied():
    from services.observability import security_audit as sa

    sa.log_action_denied(
        "delete_all", reason="policy forbids", tool="rm_tool", conversation_id="c1"
    )
    events = sa.get_recent_security_events()

    assert len(events) == 1
    evt = events[0]
    assert evt["event_type"] == "action_denied"
    assert evt["action"] == "delete_all"
    assert evt["reason"] == "policy forbids"
    assert evt["tool"] == "rm_tool"
    assert evt["conversation_id"] == "c1"


# ── 3. log_protected_file_attempt ─────────────────────────────────────────────

def test_log_protected_file_attempt():
    from services.observability import security_audit as sa

    sa.log_protected_file_attempt("/etc/shadow", tool="read_file", blocked=True)
    events = sa.get_recent_security_events()

    assert len(events) == 1
    evt = events[0]
    assert evt["event_type"] == "protected_file_attempt"
    assert evt["path"] == "/etc/shadow"
    assert evt["blocked"] is True


# ── 4. log_dangerous_tool_usage ───────────────────────────────────────────────

def test_log_dangerous_tool_usage():
    from services.observability import security_audit as sa

    sa.log_dangerous_tool_usage(
        "shell_exec", args_preview="rm -rf /", allowed=False
    )
    events = sa.get_recent_security_events()

    assert len(events) == 1
    evt = events[0]
    assert evt["event_type"] == "dangerous_tool_usage"
    assert evt["tool"] == "shell_exec"
    assert evt["args_preview"] == "rm -rf /"
    assert evt["allowed"] is False


# ── 5. log_policy_bypass_attempt ──────────────────────────────────────────────

def test_log_policy_bypass_attempt():
    from services.observability import security_audit as sa

    sa.log_policy_bypass_attempt(
        "sandbox_escape", detail="attempted chroot breakout", blocked=True
    )
    events = sa.get_recent_security_events()

    assert len(events) == 1
    evt = events[0]
    assert evt["event_type"] == "policy_bypass_attempt"
    assert evt["policy"] == "sandbox_escape"
    assert evt["detail"] == "attempted chroot breakout"
    assert evt["blocked"] is True


# ── 6. log_sandbox_violation ──────────────────────────────────────────────────

def test_log_sandbox_violation():
    from services.observability import security_audit as sa

    sa.log_sandbox_violation(
        "file_write", path="/proc/self/mem", detail="write outside sandbox"
    )
    events = sa.get_recent_security_events()

    assert len(events) == 1
    evt = events[0]
    assert evt["event_type"] == "sandbox_violation"
    assert evt["tool"] == "file_write"
    assert evt["path"] == "/proc/self/mem"
    assert evt["detail"] == "write outside sandbox"


# ── 7. get_security_summary ──────────────────────────────────────────────────

def test_get_security_summary():
    from services.observability import security_audit as sa

    sa.log_action_denied("a1")
    sa.log_action_denied("a2")
    sa.log_sandbox_violation("t1")
    sa.log_approval_escalation("t2")

    summary = sa.get_security_summary()

    assert summary["total_events"] == 4
    assert summary["by_type"]["action_denied"] == 2
    assert summary["by_type"]["sandbox_violation"] == 1
    assert summary["by_type"]["approval_escalation"] == 1
    assert summary["buffer_capacity"] == 500


# ── 8. Ring buffer limit ─────────────────────────────────────────────────────

def test_event_ring_buffer_limit():
    from services.observability import security_audit as sa

    for i in range(550):
        sa.log_action_denied(f"action_{i}")

    events = sa.get_recent_security_events(limit=600)
    assert len(events) == 500

    # Newest event should be action_549 (last inserted)
    assert events[0]["action"] == "action_549"
    # Oldest surviving event should be action_50 (first 50 were dropped)
    assert events[-1]["action"] == "action_50"


# ── 9. Fire-and-forget (never raise) ─────────────────────────────────────────

def test_events_never_raise(monkeypatch):
    from services.observability import security_audit as sa

    def _bad_record(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(sa, "_record", _bad_record)

    # None of these should raise
    sa.log_approval_escalation("t")
    sa.log_action_denied("a")
    sa.log_protected_file_attempt("p")
    sa.log_dangerous_tool_usage("d")
    sa.log_policy_bypass_attempt("pol")
    sa.log_sandbox_violation("sv")


# ── 10. Event structure ───────────────────────────────────────────────────────

def test_event_structure():
    from services.observability import security_audit as sa

    sa.log_approval_escalation("t1")
    sa.log_action_denied("a1")
    sa.log_protected_file_attempt("/x")
    sa.log_dangerous_tool_usage("d1")
    sa.log_policy_bypass_attempt("p1")
    sa.log_sandbox_violation("s1")

    events = sa.get_recent_security_events(limit=10)
    assert len(events) == 6

    for evt in events:
        assert "timestamp" in evt, f"Missing timestamp in {evt}"
        assert "event_type" in evt, f"Missing event_type in {evt}"
        # Timestamp should look like ISO 8601
        assert evt["timestamp"][4] == "-", f"Bad timestamp format: {evt['timestamp']}"
