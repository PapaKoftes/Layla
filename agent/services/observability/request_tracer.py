# -*- coding: utf-8 -*-
"""
request_tracer.py -- Per-request/per-turn observability trace.

Each call to autonomous_run or stream_reason opens a trace that records:
  - request_id        -- UUID4 short (8 chars); correlates log lines to this turn
  - aspect_id         -- which aspect handled the request
  - reasoning_mode    -- none / light / deep
  - phase timings     -- retrieval_ms, llm_ms, tools_ms, total_ms
  - per-turn tokens   -- prompt_tokens, completion_tokens used THIS turn only
  - tool_calls        -- how many tool calls this turn
  - status            -- ok / error / busy / refused
  - goal_preview      -- first 80 chars of goal

All state lives in a ContextVar so concurrent requests never bleed into
each other. Completed traces are appended to a bounded in-memory ring
(last 200) queryable via get_recent_traces().

Phases:
  "retrieval"  -- ChromaDB / memory semantic recall
  "llm"        -- actual LLM inference (run_completion)
  "tools"      -- all tool executions in this turn
  "planning"   -- planner / plan execution overhead
  "total"      -- wall time for the full autonomous_run call

Usage:
    # At turn start:
    trace = start_trace(goal, aspect_id=aid, reasoning_mode=rmode)

    # Time a phase:
    with trace_phase(trace, "retrieval"):
        results = semantic_recall(goal)

    # Record tokens (called from llm_gateway):
    record_trace_tokens(prompt_tokens=N, completion_tokens=M)

    # At turn end:
    finish_trace(trace, status="ok", tool_calls=N)
"""
from __future__ import annotations

import collections
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Active trace ContextVar
# ---------------------------------------------------------------------------

_active_trace: ContextVar[dict | None] = ContextVar("layla_active_trace", default=None)

# ---------------------------------------------------------------------------
# Completed traces ring buffer (thread-safe, max 200)
# ---------------------------------------------------------------------------

_traces_lock = threading.Lock()
_traces_ring: collections.deque[dict] = collections.deque(maxlen=200)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _short_id() -> str:
    return str(uuid.uuid4()).replace("-", "")[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_trace(goal: str, aspect_id: str, reasoning_mode: str) -> dict:
    return {
        "request_id":        _short_id(),
        "started_at":        _now_iso(),
        "finished_at":       "",
        "goal_preview":      (goal or "")[:80],
        "aspect_id":         aspect_id or "",
        "reasoning_mode":    reasoning_mode or "",
        "status":            "in_progress",
        "prompt_tokens":     0,
        "completion_tokens": 0,
        "total_tokens":      0,
        "tool_calls":        0,
        "phases": {
            "retrieval_ms": 0.0,
            "llm_ms":       0.0,
            "tools_ms":     0.0,
            "planning_ms":  0.0,
            "total_ms":     0.0,
        },
        "_t0": time.monotonic(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_trace(
    goal: str,
    aspect_id: str = "",
    reasoning_mode: str = "",
) -> dict:
    """
    Open a new per-turn trace and set it as the active ContextVar trace.
    Returns the trace dict so the caller can pass it to finish_trace.
    """
    trace = _empty_trace(goal, aspect_id, reasoning_mode)
    _active_trace.set(trace)
    return trace


def get_active_trace() -> dict | None:
    """Return the active trace for the current context, or None."""
    return _active_trace.get()


def record_trace_tokens(prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """
    Add token counts to the active trace. Safe to call from llm_gateway.
    No-op if no active trace.
    """
    trace = _active_trace.get()
    if trace is None:
        return
    try:
        trace["prompt_tokens"]     += max(0, int(prompt_tokens))
        trace["completion_tokens"] += max(0, int(completion_tokens))
        trace["total_tokens"]       = trace["prompt_tokens"] + trace["completion_tokens"]
    except Exception:
        pass


def record_trace_tool_call() -> None:
    """Increment the tool_calls counter in the active trace."""
    trace = _active_trace.get()
    if trace is None:
        return
    try:
        trace["tool_calls"] += 1
    except Exception:
        pass


@contextmanager
def trace_phase(trace: dict | None, phase: str):
    """
    Context manager to time a phase block and accumulate into trace["phases"].

    Usage:
        with trace_phase(trace, "retrieval"):
            results = semantic_recall(goal)

    Safe if trace is None (no-op).
    """
    if trace is None:
        yield
        return
    key = f"{phase}_ms"
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = (time.monotonic() - t0) * 1000.0
        phases = trace.get("phases")
        if isinstance(phases, dict):
            phases[key] = round(phases.get(key, 0.0) + elapsed, 2)


def finish_trace(
    trace: dict | None,
    status: str = "ok",
    tool_calls: int | None = None,
) -> dict | None:
    """
    Close the trace, compute total_ms, and append to the ring buffer.
    Clears the ContextVar. Returns the completed trace dict.
    """
    if trace is None:
        return None
    try:
        t0 = trace.get("_t0") or time.monotonic()
        total_ms = round((time.monotonic() - t0) * 1000.0, 2)
        trace["phases"]["total_ms"] = total_ms
        trace["finished_at"] = _now_iso()
        trace["status"] = status or "ok"
        if tool_calls is not None:
            trace["tool_calls"] = int(tool_calls)
        # Remove internal fields before archiving
        trace.pop("_t0", None)
        with _traces_lock:
            _traces_ring.append(dict(trace))
        _active_trace.set(None)
    except Exception as e:
        logger.debug("request_tracer finish_trace failed: %s", e)
    return trace


def get_recent_traces(n: int = 20) -> list[dict]:
    """Return up to n most-recent completed traces, newest first."""
    with _traces_lock:
        items = list(_traces_ring)
    items.reverse()
    return items[:max(1, int(n))]


def get_trace_summary(trace: dict) -> str:
    """One-line human-readable summary of a completed trace."""
    if not trace:
        return ""
    rid   = trace.get("request_id", "?")
    asp   = trace.get("aspect_id", "?")
    mode  = trace.get("reasoning_mode", "?")
    tok   = trace.get("total_tokens", 0)
    tools = trace.get("tool_calls", 0)
    ms    = (trace.get("phases") or {}).get("total_ms", 0)
    st    = trace.get("status", "?")
    goal  = trace.get("goal_preview", "")[:40]
    return (
        f"[{rid}] {asp}/{mode} | {tok}tok {tools}tools {ms:.0f}ms | "
        f"{st} | \"{goal}\""
    )


def clear_traces() -> int:
    """Clear the ring buffer. Returns count removed."""
    with _traces_lock:
        n = len(_traces_ring)
        _traces_ring.clear()
    return n
