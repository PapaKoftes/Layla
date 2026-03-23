"""Tests for cancellation support in shared_state.py."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_new_cancel_event_returns_event():
    from shared_state import new_cancel_event
    ev = new_cancel_event("test-conv-1")
    assert hasattr(ev, "is_set")
    assert not ev.is_set()


def test_set_cancel_sets_event():
    from shared_state import get_cancel_event, new_cancel_event, set_cancel
    ev = new_cancel_event("test-conv-2")
    assert not ev.is_set()
    found = set_cancel("test-conv-2")
    assert found is True
    assert ev.is_set()


def test_set_cancel_missing_conv_returns_false():
    from shared_state import set_cancel
    found = set_cancel("does-not-exist-99999")
    assert found is False


def test_clear_cancel_removes_event():
    from shared_state import clear_cancel, get_cancel_event, new_cancel_event
    new_cancel_event("test-conv-3")
    clear_cancel("test-conv-3")
    assert get_cancel_event("test-conv-3") is None


def test_get_most_recent_conv_id():
    from shared_state import get_most_recent_conv_id, new_cancel_event
    new_cancel_event("test-conv-4")
    new_cancel_event("test-conv-5")
    assert get_most_recent_conv_id() == "test-conv-5"


def test_cancel_event_stops_loop():
    """Simulate: cancel_event.is_set() stops a decision loop early."""
    from shared_state import new_cancel_event, set_cancel

    ev = new_cancel_event("test-conv-loop")
    iterations = 0
    for _ in range(10):
        if ev.is_set():
            break
        iterations += 1
        if iterations == 3:
            set_cancel("test-conv-loop")

    # Should have stopped after 3 iterations (cancelled on 4th check)
    assert ev.is_set()
    assert iterations == 3
