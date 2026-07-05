"""Shared goal contextvars (BL-121).

The user's goal is captured, then optionally rewritten by the optimizer. Both the
original and the optimized text must stay reachable across the run (memory writes,
reflection, trace endpoints). These contextvars live here — a neutral module — so
services no longer reach into `agent_loop`'s privates to read them; `agent_loop`
re-exports them for backward compatibility.
"""
from __future__ import annotations

from contextvars import ContextVar

_goal_original_var: ContextVar[str] = ContextVar("layla_goal_original", default="")
_goal_optimized_var: ContextVar[str] = ContextVar("layla_goal_optimized", default="")


def get_last_goal_original() -> str:
    """The most recent user-authored goal (pre-optimizer)."""
    return _goal_original_var.get()


def get_last_goal_optimized() -> str:
    """The optimizer's rewrite of the most recent goal."""
    return _goal_optimized_var.get()
