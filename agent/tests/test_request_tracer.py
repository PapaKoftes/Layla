# -*- coding: utf-8 -*-
"""
test_request_tracer.py -- Unit tests for per-request observability tracer.

Tests trace lifecycle, token accumulation, phase timing, ring buffer,
concurrency isolation, and the /health/trace endpoint.

Run:
    cd agent/ && python -m pytest tests/test_request_tracer.py -v
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.request_tracer import (
    clear_traces,
    finish_trace,
    get_active_trace,
    get_recent_traces,
    get_trace_summary,
    record_trace_tokens,
    record_trace_tool_call,
    start_trace,
    trace_phase,
)


@pytest.fixture(autouse=True)
def _clear_ring():
    """Start each test with a clean ring buffer and no active trace."""
    clear_traces()
    # Reset ContextVar -- start_trace sets it; finish_trace clears it.
    # If a previous test left an active trace, clear it by finishing a dummy.
    finish_trace(get_active_trace(), status="cleared")
    yield
    clear_traces()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_start_trace_returns_dict():
    t = start_trace("fix the bug", aspect_id="morrigan", reasoning_mode="deep")
    assert isinstance(t, dict)
    assert t["goal_preview"] == "fix the bug"
    assert t["aspect_id"] == "morrigan"
    assert t["reasoning_mode"] == "deep"
    assert t["status"] == "in_progress"
    finish_trace(t)


def test_start_trace_sets_context():
    t = start_trace("hello")
    assert get_active_trace() is t
    finish_trace(t)
    assert get_active_trace() is None


def test_finish_trace_sets_status():
    t = start_trace("do work")
    finish_trace(t, status="ok")
    assert t["status"] == "ok"


def test_finish_trace_populates_total_ms():
    t = start_trace("do work")
    time.sleep(0.01)
    finish_trace(t)
    assert t["phases"]["total_ms"] >= 1.0


def test_finish_trace_records_tool_calls():
    t = start_trace("run tests")
    finish_trace(t, status="ok", tool_calls=3)
    assert t["tool_calls"] == 3


def test_finish_none_is_safe():
    result = finish_trace(None)
    assert result is None


def test_finish_twice_is_safe():
    t = start_trace("safe test")
    finish_trace(t, status="ok")
    finish_trace(t, status="ok")  # should not raise


# ---------------------------------------------------------------------------
# Token recording
# ---------------------------------------------------------------------------

def test_record_tokens_accumulates():
    t = start_trace("token test")
    record_trace_tokens(prompt_tokens=100, completion_tokens=50)
    record_trace_tokens(prompt_tokens=200, completion_tokens=80)
    assert t["prompt_tokens"] == 300
    assert t["completion_tokens"] == 130
    assert t["total_tokens"] == 430
    finish_trace(t)


def test_record_tokens_no_active_trace_is_safe():
    # No active trace -- should not raise
    finish_trace(get_active_trace(), status="cleared")
    record_trace_tokens(100, 50)  # no-op


def test_record_tool_call_increments():
    t = start_trace("tool call test")
    record_trace_tool_call()
    record_trace_tool_call()
    assert t["tool_calls"] == 2
    finish_trace(t)


def test_record_tool_call_no_active_trace_is_safe():
    finish_trace(get_active_trace(), status="cleared")
    record_trace_tool_call()  # no-op


# ---------------------------------------------------------------------------
# Phase timing
# ---------------------------------------------------------------------------

def test_trace_phase_accumulates_ms():
    t = start_trace("phase test")
    with trace_phase(t, "retrieval"):
        time.sleep(0.01)
    assert t["phases"]["retrieval_ms"] >= 1.0
    finish_trace(t)


def test_trace_phase_multiple_calls_sum():
    t = start_trace("phase sum test")
    with trace_phase(t, "llm"):
        time.sleep(0.005)
    with trace_phase(t, "llm"):
        time.sleep(0.005)
    assert t["phases"]["llm_ms"] >= 5.0
    finish_trace(t)


def test_trace_phase_none_is_safe():
    with trace_phase(None, "retrieval"):
        pass  # should not raise


def test_trace_phase_exception_still_records():
    t = start_trace("exception test")
    try:
        with trace_phase(t, "tools"):
            time.sleep(0.005)
            raise ValueError("oops")
    except ValueError:
        pass
    assert t["phases"]["tools_ms"] >= 1.0
    finish_trace(t, status="error")


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------

def test_completed_trace_in_ring():
    t = start_trace("ring test")
    finish_trace(t, status="ok")
    recent = get_recent_traces(n=10)
    assert len(recent) >= 1
    assert recent[0]["status"] == "ok"


def test_get_recent_traces_newest_first():
    for i in range(5):
        t = start_trace(f"run {i}")
        finish_trace(t, status="ok")
    recent = get_recent_traces(n=5)
    goals = [r["goal_preview"] for r in recent]
    assert goals[0] == "run 4"
    assert goals[-1] == "run 0"


def test_ring_capped_at_200():
    clear_traces()
    for i in range(210):
        t = start_trace(f"bulk {i}")
        finish_trace(t)
    recent = get_recent_traces(n=500)
    assert len(recent) <= 200


def test_clear_traces_empties_ring():
    t = start_trace("temp")
    finish_trace(t)
    n = clear_traces()
    assert n >= 1
    assert get_recent_traces() == []


# ---------------------------------------------------------------------------
# get_trace_summary
# ---------------------------------------------------------------------------

def test_summary_contains_key_fields():
    t = start_trace("summarise this goal text here", aspect_id="nyx", reasoning_mode="deep")
    record_trace_tokens(500, 200)
    record_trace_tool_call()
    finish_trace(t, status="ok")
    s = get_trace_summary(t)
    assert "nyx" in s
    assert "deep" in s
    assert "700" in s or "tok" in s
    assert "ok" in s


def test_summary_empty_trace():
    assert get_trace_summary({}) == ""
    assert get_trace_summary(None) == ""


# ---------------------------------------------------------------------------
# Concurrency isolation (ContextVar)
# ---------------------------------------------------------------------------

def test_concurrent_traces_isolated():
    """Two threads must not share trace state."""
    results = {}

    def worker(name, sleep_s):
        t = start_trace(f"goal from {name}")
        time.sleep(sleep_s)
        record_trace_tokens(prompt_tokens=100 if name == "A" else 200, completion_tokens=0)
        finish_trace(t, status="ok")
        results[name] = t["prompt_tokens"]

    ta = threading.Thread(target=worker, args=("A", 0.02))
    tb = threading.Thread(target=worker, args=("B", 0.01))
    ta.start()
    tb.start()
    ta.join()
    tb.join()

    assert results["A"] == 100
    assert results["B"] == 200


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------

@pytest.mark.endpoint
def test_health_trace_endpoint(client):
    t = start_trace("endpoint test goal")
    record_trace_tokens(300, 100)
    finish_trace(t, status="ok", tool_calls=2)

    r = client.get("/health/trace?n=5")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert isinstance(data["traces"], list)
    if data["traces"]:
        first = data["traces"][0]
        assert "request_id" in first
        assert "phases" in first


def test_health_trace_summary_format(client):
    t = start_trace("summary format test")
    finish_trace(t, status="ok")

    r = client.get("/health/trace?n=3&fmt=summary")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    if data["traces"]:
        assert isinstance(data["traces"][0], str)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
