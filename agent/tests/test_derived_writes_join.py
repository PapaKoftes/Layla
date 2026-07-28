# -*- coding: utf-8 -*-
"""
ST-3 regression: derived-memory writers must be joinable at shutdown.

Title synthesis, skill acquisition, learning extraction and capability practice run on daemon
threads (so a hung LLM call can never block interpreter exit). Daemon threads are killed instantly
at exit, so closing the window right after a turn used to silently drop that turn's derived memory.
`_spawn_derived` registers each writer and `join_derived_writes` gives them a brief, bounded chance
to finish at shutdown — while keeping them daemon so exit can never hang.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import pytest  # noqa: E402

from services.agent import turn_commit as tc  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_registry():
    """The registry is module-global and other tests (which monkeypatch threading.Thread) can leave
    doubles in it. Clear it around each test so these assertions are deterministic."""
    with tc._DERIVED_LOCK:
        tc._DERIVED_THREADS.clear()
    yield
    with tc._DERIVED_LOCK:
        tc._DERIVED_THREADS.clear()


def test_spawn_derived_thread_is_daemon_and_registered():
    done = threading.Event()
    t = tc._spawn_derived(done.set, name="test-writer")
    try:
        assert t.daemon is True, "derived writers must stay daemon so exit can't hang"
        assert done.wait(timeout=2.0), "the spawned target should have run"
    finally:
        t.join(timeout=2.0)


def test_join_waits_for_a_slow_writer_within_budget():
    landed = threading.Event()

    def _slow():
        time.sleep(0.2)
        landed.set()

    tc._spawn_derived(_slow, name="slow-writer")
    still_alive = tc.join_derived_writes(timeout_total=2.0)
    assert landed.is_set(), "join must give an in-flight writer time to finish"
    assert still_alive == 0


def test_register_derived_thread_is_covered_by_join():
    # ST-3: writers spawned outside _spawn_derived (non-streamed skill-acquire, entity extractor)
    # register via register_derived_thread and must be waited on by join_derived_writes.
    landed = threading.Event()

    def _slow():
        time.sleep(0.15)
        landed.set()

    t = threading.Thread(target=_slow, daemon=True, name="external-writer")
    t.start()
    tc.register_derived_thread(t)
    still = tc.join_derived_writes(timeout_total=2.0)
    assert landed.is_set(), "an externally-registered writer must be joined at shutdown"
    assert still == 0


def test_register_derived_thread_ignores_none_and_thread_doubles():
    tc.register_derived_thread(None)  # must not crash

    class _Double:  # a start()-only test double, no is_alive()
        def start(self):
            pass

    tc.register_derived_thread(_Double())
    # The double must be treated as not-alive and never crash the join/prune.
    assert tc.join_derived_writes(timeout_total=0.1) == 0


def test_entity_extractor_returns_a_registerable_thread(monkeypatch):
    from services.memory import conversation_entity_extractor as cee

    monkeypatch.setattr(cee, "extract_and_store", lambda *a, **k: None)
    t = cee.extract_in_background("u", "a", conversation_id="c", aspect_id="x")
    assert t is not None and hasattr(t, "join"), "extract_in_background must return its thread for ST-3 registration"
    t.join(timeout=2.0)


def test_join_is_bounded_and_never_hangs_on_a_stuck_writer():
    release = threading.Event()

    def _stuck():
        release.wait(timeout=30)  # would outlive any reasonable shutdown budget

    tc._spawn_derived(_stuck, name="stuck-writer")
    t0 = time.monotonic()
    still_alive = tc.join_derived_writes(timeout_total=0.3)
    elapsed = time.monotonic() - t0
    try:
        assert elapsed < 2.0, "join must return within roughly the budget, not block on a stuck writer"
        assert still_alive >= 1, "a stuck writer should be reported as still-alive"
    finally:
        release.set()  # let the stuck thread exit so it doesn't linger
