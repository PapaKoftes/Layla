"""Tests for shared_state.py — steer hints, conversation history, outcome eval, blackboard, leases, cancellation."""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

import shared_state as ss

# ---------------------------------------------------------------------------
# Helpers — reset module-level dicts between tests to avoid cross-pollution
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Clear all in-process shared state between tests."""
    with ss._steer_lock:
        ss._steer_hints.clear()
    with ss._conv_hist_lock:
        ss._conv_histories.clear()
    with ss._outcome_eval_lock:
        ss._last_outcome_evaluation.clear()
    with ss._coordinator_trace_lock:
        ss._last_coordinator_trace.clear()
    with ss._execution_snap_lock:
        ss._last_execution_snapshot.clear()
    with ss._decision_trace_lock:
        ss._last_decision_trace.clear()
    with ss._bb_lock:
        ss._blackboard.clear()
    with ss._workspace_lease_lock:
        ss._workspace_lease.clear()
    with ss._cancel_lock:
        ss._cancel_events.clear()
        ss._most_recent_conv_id = None
    # ADR-002: also reset the new SessionContext store (steer hints etc. live here now)
    try:
        from services.infrastructure import session_context as _sc
        with _sc._sessions_lock:
            _sc._sessions.clear()
    except Exception:
        pass
    yield


# ===========================================================================
# Steer hints
# ===========================================================================


class TestSteerHints:
    """Push/pop FIFO queue with max-8 overflow."""

    def test_push_pop_fifo_order(self):
        ss.push_agent_steer_hint("conv1", "first")
        ss.push_agent_steer_hint("conv1", "second")
        ss.push_agent_steer_hint("conv1", "third")

        assert ss.pop_one_agent_steer_hint("conv1") == "first"
        assert ss.pop_one_agent_steer_hint("conv1") == "second"
        assert ss.pop_one_agent_steer_hint("conv1") == "third"

    def test_overflow_8_limit(self):
        for i in range(12):
            ss.push_agent_steer_hint("conv1", f"msg-{i}")

        # Oldest 4 should have been dropped; 8 remain (msg-4..msg-11)
        first = ss.pop_one_agent_steer_hint("conv1")
        assert first == "msg-4"

    def test_empty_returns_empty_string(self):
        assert ss.pop_one_agent_steer_hint("nonexistent") == ""

    def test_empty_text_ignored(self):
        ss.push_agent_steer_hint("conv1", "")
        ss.push_agent_steer_hint("conv1", "   ")
        assert ss.pop_one_agent_steer_hint("conv1") == ""

    def test_per_conversation_isolation(self):
        ss.push_agent_steer_hint("conv-a", "hint-a")
        ss.push_agent_steer_hint("conv-b", "hint-b")

        assert ss.pop_one_agent_steer_hint("conv-a") == "hint-a"
        assert ss.pop_one_agent_steer_hint("conv-b") == "hint-b"

    def test_truncates_long_text(self):
        long_text = "x" * 500
        ss.push_agent_steer_hint("conv1", long_text)
        result = ss.pop_one_agent_steer_hint("conv1")
        assert len(result) <= 280


# ===========================================================================
# Conversation history
# ===========================================================================


class TestConvHistory:
    """get_conv_history and append_conv_history."""

    @patch("layla.memory.conversations.get_conversation_messages", return_value=[])
    def test_creates_new_deque(self, _mock_db):
        hist = ss.get_conv_history("brand-new")
        assert len(hist) == 0
        assert hasattr(hist, "maxlen")

    @patch("layla.memory.conversations.get_conversation_messages", return_value=[])
    def test_per_conversation_isolation(self, _mock_db):
        hist_a = ss.get_conv_history("conv-a")
        hist_b = ss.get_conv_history("conv-b")
        with ss._conv_hist_lock:
            hist_a.append({"role": "user", "content": "only in A"})
        assert len(hist_b) == 0

    @patch("layla.memory.conversations.get_conversation_messages", return_value=[])
    @patch("services.context.context_manager.maybe_auto_compact", side_effect=lambda msgs, **kw: msgs)
    @patch("runtime_safety.load_config", return_value={"n_ctx": 4096})
    def test_append_adds_messages(self, _mock_cfg, _mock_compact, _mock_db):
        ss.append_conv_history("conv1", "user", "Hello")
        hist = ss.get_conv_history("conv1")
        assert len(hist) >= 1
        found = any(m["content"] == "Hello" for m in hist)
        assert found

    @patch("layla.memory.conversations.get_conversation_messages", return_value=[
        {"role": "user", "content": "Restored from DB"},
    ])
    def test_loads_from_db_on_first_access(self, mock_db):
        hist = ss.get_conv_history("restored-conv")
        # The fixture should have loaded the DB row into the deque
        assert any(m.get("content") == "Restored from DB" for m in hist)
        mock_db.assert_called_once()


# ===========================================================================
# Outcome evaluation
# ===========================================================================


class TestOutcomeEvaluation:
    """set/get/clear_last_outcome_evaluation."""

    @patch("layla.memory.db.save_outcome_evaluation")
    @patch("layla.memory.db.get_last_outcome_evaluation_record", return_value=None)
    def test_roundtrip(self, _mock_get, _mock_save):
        data = {"success": True, "score": 0.9}
        ss.set_last_outcome_evaluation("conv1", data)
        result = ss.get_last_outcome_evaluation("conv1")
        assert result == data

    @patch("layla.memory.db.save_outcome_evaluation")
    @patch("layla.memory.db.get_last_outcome_evaluation_record", return_value=None)
    def test_isolation_between_convs(self, _mock_get, _mock_save):
        ss.set_last_outcome_evaluation("conv-a", {"score": 0.5})
        ss.set_last_outcome_evaluation("conv-b", {"score": 0.9})

        assert ss.get_last_outcome_evaluation("conv-a")["score"] == 0.5
        assert ss.get_last_outcome_evaluation("conv-b")["score"] == 0.9

    @patch("layla.memory.db.save_outcome_evaluation")
    @patch("layla.memory.db.get_last_outcome_evaluation_record", return_value=None)
    def test_clear(self, _mock_get, _mock_save):
        ss.set_last_outcome_evaluation("conv1", {"score": 1.0})
        ss.clear_last_outcome_evaluation("conv1")
        assert ss.get_last_outcome_evaluation("conv1") is None

    @patch("layla.memory.db.get_last_outcome_evaluation_record", return_value={"score": 0.7, "from_db": True})
    def test_falls_back_to_db(self, mock_get):
        """When not in memory, get_last_outcome_evaluation queries the DB."""
        result = ss.get_last_outcome_evaluation("conv-from-db")
        assert result is not None
        assert result["from_db"] is True
        mock_get.assert_called_once_with("conv-from-db")

    def test_non_dict_data_ignored(self):
        ss.set_last_outcome_evaluation("conv1", "not a dict")  # type: ignore[arg-type]
        # Should silently ignore non-dict
        with patch("layla.memory.db.get_last_outcome_evaluation_record", return_value=None):
            assert ss.get_last_outcome_evaluation("conv1") is None


# ===========================================================================
# Coordinator trace
# ===========================================================================


class TestCoordinatorTrace:
    """set/get/clear_last_coordinator_trace."""

    def test_roundtrip(self):
        data = {"classifier": "task", "confidence": 0.95}
        ss.set_last_coordinator_trace("conv1", data)
        result = ss.get_last_coordinator_trace("conv1")
        assert result == data

    def test_clear(self):
        ss.set_last_coordinator_trace("conv1", {"x": 1})
        ss.clear_last_coordinator_trace("conv1")
        assert ss.get_last_coordinator_trace("conv1") is None

    def test_returns_copy(self):
        data = {"key": "value"}
        ss.set_last_coordinator_trace("conv1", data)
        result = ss.get_last_coordinator_trace("conv1")
        result["key"] = "mutated"
        # Original should be unaffected
        assert ss.get_last_coordinator_trace("conv1")["key"] == "value"


# ===========================================================================
# Execution snapshot
# ===========================================================================


class TestExecutionSnapshot:
    """set/get/clear_last_execution_snapshot."""

    def test_roundtrip(self):
        data = {"steps": 5, "status": "running"}
        ss.set_last_execution_snapshot("conv1", data)
        result = ss.get_last_execution_snapshot("conv1")
        assert result == data

    def test_clear(self):
        ss.set_last_execution_snapshot("conv1", {"x": 1})
        ss.clear_last_execution_snapshot("conv1")
        assert ss.get_last_execution_snapshot("conv1") is None


# ===========================================================================
# Decision trace
# ===========================================================================


class TestDecisionTrace:
    """set/get_last_decision_trace."""

    def test_roundtrip(self):
        traces = [{"gate": "safety", "passed": True}, {"gate": "budget", "passed": False}]
        ss.set_last_decision_trace("conv1", traces)
        result = ss.get_last_decision_trace("conv1")
        assert result == traces

    def test_returns_copy(self):
        traces = [{"gate": "a"}]
        ss.set_last_decision_trace("conv1", traces)
        result = ss.get_last_decision_trace("conv1")
        result.append({"gate": "mutated"})
        assert len(ss.get_last_decision_trace("conv1")) == 1

    def test_non_list_ignored(self):
        ss.set_last_decision_trace("conv1", "not a list")  # type: ignore[arg-type]
        assert ss.get_last_decision_trace("conv1") is None


# ===========================================================================
# Blackboard
# ===========================================================================


class TestBlackboard:
    """blackboard_put/get/clear with namespace isolation."""

    def test_put_and_get(self):
        ss.blackboard_put("job1", "progress", 42)
        result = ss.blackboard_get("job1")
        assert result["progress"] == 42

    def test_clear(self):
        ss.blackboard_put("job1", "key", "value")
        ss.blackboard_clear("job1")
        result = ss.blackboard_get("job1")
        assert "key" not in result

    def test_namespace_isolation(self):
        ss.blackboard_put("job-a", "data", "alpha")
        ss.blackboard_put("job-b", "data", "bravo")

        assert ss.blackboard_get("job-a")["data"] == "alpha"
        assert ss.blackboard_get("job-b")["data"] == "bravo"

    def test_empty_key_ignored(self):
        ss.blackboard_put("job1", "", "value")
        result = ss.blackboard_get("job1")
        # Empty key should not be stored (beyond metadata)
        assert "" not in result

    def test_holder_recorded(self):
        ss.blackboard_put("job1", "key", "val", holder="worker-7")
        result = ss.blackboard_get("job1")
        assert result["_holder"] == "worker-7"

    def test_get_nonexistent_returns_empty_dict(self):
        result = ss.blackboard_get("no-such-job")
        assert result == {}

    def test_returns_copy(self):
        ss.blackboard_put("job1", "x", 1)
        result = ss.blackboard_get("job1")
        result["x"] = 999
        assert ss.blackboard_get("job1")["x"] == 1


# ===========================================================================
# Workspace lease
# ===========================================================================


class TestWorkspaceLease:
    """try_acquire_workspace_lease / release_workspace_lease."""

    def test_acquire_and_release(self):
        acquired = ss.try_acquire_workspace_lease("/project", "holder-1")
        assert acquired is True
        ss.release_workspace_lease("/project", "holder-1")

    def test_same_holder_re_acquires(self):
        ss.try_acquire_workspace_lease("/project", "holder-1")
        # Same holder can "re-acquire" (idempotent)
        acquired = ss.try_acquire_workspace_lease("/project", "holder-1")
        assert acquired is True

    def test_different_holder_blocked(self):
        ss.try_acquire_workspace_lease("/project", "holder-1", ttl_seconds=3600)
        acquired = ss.try_acquire_workspace_lease("/project", "holder-2")
        assert acquired is False

    def test_ttl_expiry(self):
        """After TTL expires, a new holder can acquire."""
        base = time.monotonic()

        with patch("time.monotonic", return_value=base):
            ss.try_acquire_workspace_lease("/project", "holder-1", ttl_seconds=30)

        # Simulate time advancing past the TTL (base + 30 seconds)
        with patch("time.monotonic", return_value=base + 9999):
            acquired = ss.try_acquire_workspace_lease("/project", "holder-2", ttl_seconds=60)

        assert acquired is True

    def test_holder_matching(self):
        """Release only works when holder matches."""
        ss.try_acquire_workspace_lease("/project", "holder-1")
        # Wrong holder cannot release
        ss.release_workspace_lease("/project", "wrong-holder")
        # holder-1 should still hold the lease → holder-2 blocked
        acquired = ss.try_acquire_workspace_lease("/project", "holder-2")
        assert acquired is False

    def test_empty_workspace_returns_false(self):
        assert ss.try_acquire_workspace_lease("", "holder") is False

    def test_empty_holder_returns_false(self):
        assert ss.try_acquire_workspace_lease("/project", "") is False


# ===========================================================================
# Cancellation
# ===========================================================================


class TestCancellation:
    """new_cancel_event / get_cancel_event / set_cancel / clear_cancel."""

    def test_lifecycle(self):
        ev = ss.new_cancel_event("conv1")
        assert isinstance(ev, asyncio.Event)
        assert not ev.is_set()

        # Retrieve it
        retrieved = ss.get_cancel_event("conv1")
        assert retrieved is ev

        # Signal cancellation
        result = ss.set_cancel("conv1")
        assert result is True
        assert ev.is_set()

        # Clear
        ss.clear_cancel("conv1")
        assert ss.get_cancel_event("conv1") is None

    def test_set_cancel_nonexistent_returns_false(self):
        assert ss.set_cancel("no-such-conv") is False

    def test_new_resets_event(self):
        ev1 = ss.new_cancel_event("conv1")
        ev1.set()
        assert ev1.is_set()

        ev2 = ss.new_cancel_event("conv1")
        assert not ev2.is_set()
        # Should be a fresh event
        assert ev2 is not ev1

    def test_get_nonexistent_returns_none(self):
        assert ss.get_cancel_event("nonexistent") is None


# ===========================================================================
# Most recent conversation ID
# ===========================================================================


class TestMostRecentConvId:
    """get_most_recent_conv_id tracks the latest new_cancel_event call."""

    def test_tracks_latest(self):
        assert ss.get_most_recent_conv_id() is None

        ss.new_cancel_event("conv-1")
        assert ss.get_most_recent_conv_id() == "conv-1"

        ss.new_cancel_event("conv-2")
        assert ss.get_most_recent_conv_id() == "conv-2"

    def test_clear_does_not_reset_most_recent(self):
        ss.new_cancel_event("conv-1")
        ss.clear_cancel("conv-1")
        # most_recent_conv_id should still be "conv-1"
        assert ss.get_most_recent_conv_id() == "conv-1"


def test_autocompact_preserves_turns_appended_during_summarization(monkeypatch):
    # audit #12: maybe_auto_compact runs the LLM summarizer with the history lock RELEASED. A turn that
    # arrives during that window must NOT be wiped by the subsequent clear()+repopulate from the stale
    # pre-summary snapshot. We run the daemon compaction synchronously and simulate the race.
    import shared_state as ss

    cid = "compact-race-test"
    ss._conv_histories.pop(cid, None)

    # Run the compaction "thread" synchronously so the test is deterministic.
    class _SyncThread:
        def __init__(self, target=None, args=(), **kw):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)

    monkeypatch.setattr("threading.Thread", _SyncThread)

    # During "summarization", a new turn arrives on the live deque.
    def _fake_compact(snapshot, **kw):
        with ss._conv_hist_lock:
            ss._conv_histories[cid].append({"role": "user", "content": "RACE_TURN"})
        return list(snapshot)

    monkeypatch.setattr("services.context.context_manager.maybe_auto_compact", _fake_compact)

    ss.append_conv_history(cid, "user", "hello")
    ss.append_conv_history(cid, "assistant", "hi there")  # assistant turn triggers compaction (sync here)

    contents = [m["content"] for m in list(ss._conv_histories[cid])]
    # The turn that arrived during summarization survives (was NOT clobbered by the stale-snapshot swap).
    assert "RACE_TURN" in contents
    assert "hello" in contents and "hi there" in contents
