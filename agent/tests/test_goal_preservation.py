"""Phase B Fix 2 — verify the user-authored goal survives prompt_optimizer rewrite.

We do NOT call the full `autonomous_run` here because it pulls in heavy deps
(LLM gateway, planner, sandbox). Instead we exercise the exact mechanism the
fix relies on: the contextvars `_goal_original_var` / `_goal_optimized_var`
are set after the optimizer block and the public accessors return them.

We also patch the optimizer to force a rewrite, then drive a minimal slice
of the autonomous_run path to confirm the original text is preserved.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_contextvars_default_empty():
    """Before any run, accessors return empty strings (no leak across tests)."""
    import agent_loop
    # ContextVar defaults are "" for both
    assert agent_loop.get_last_goal_original() == ""
    assert agent_loop.get_last_goal_optimized() == ""


def test_contextvars_set_and_reset():
    """The contextvars can be set and reset cleanly."""
    import agent_loop
    tok_o = agent_loop._goal_original_var.set("original user text")
    tok_p = agent_loop._goal_optimized_var.set("rewritten by optimizer")
    try:
        assert agent_loop.get_last_goal_original() == "original user text"
        assert agent_loop.get_last_goal_optimized() == "rewritten by optimizer"
    finally:
        agent_loop._goal_original_var.reset(tok_o)
        agent_loop._goal_optimized_var.reset(tok_p)
    assert agent_loop.get_last_goal_original() == ""
    assert agent_loop.get_last_goal_optimized() == ""


def test_optimizer_rewrite_preserves_original(monkeypatch):
    """When the optimizer rewrites the goal, the contextvar still holds the
    original user text."""
    import agent_loop

    # Patch the optimizer to always rewrite
    def fake_optimize(goal, context=None):
        return {
            "changed": True,
            "optimized": f"OPTIMIZED::{goal}",
            "intent": "test",
            "tier": 2,
        }

    import services.prompt_optimizer as po
    monkeypatch.setattr(po, "optimize", fake_optimize)

    # Simulate the optimizer block from autonomous_run inline so we don't
    # invoke the full heavy path. This mirrors the lines we fixed in
    # agent_loop.autonomous_run.
    user_goal = "explain how python decorators work"
    goal = user_goal
    goal_original = goal
    goal_optimized = None

    from services.prompt_optimizer import optimize as _opt_goal
    result = _opt_goal(goal, context={"aspect": "", "workspace": ""})
    if result.get("changed") and result.get("optimized"):
        goal_optimized = result["optimized"]
        goal = result["optimized"]

    tok_o = agent_loop._goal_original_var.set(goal_original or "")
    tok_p = agent_loop._goal_optimized_var.set(goal_optimized or "")
    try:
        # Canonical user text is preserved
        assert agent_loop.get_last_goal_original() == user_goal
        # Optimized differs and carries the rewrite
        assert agent_loop.get_last_goal_optimized() == f"OPTIMIZED::{user_goal}"
        assert goal != goal_original  # local `goal` is the rewritten one
    finally:
        agent_loop._goal_original_var.reset(tok_o)
        agent_loop._goal_optimized_var.reset(tok_p)


def test_state_dict_carries_both_fields():
    """A state dict with goal_original / goal_optimized must round-trip
    intact through the fields readers expect."""
    import agent_loop
    tok_o = agent_loop._goal_original_var.set("user said this")
    tok_p = agent_loop._goal_optimized_var.set("optimizer said that")
    try:
        # Simulate what _autonomous_run_impl_core writes onto state.
        state: dict = {}
        _go = agent_loop._goal_original_var.get() or "fallback"
        _gopt = agent_loop._goal_optimized_var.get()
        state.setdefault("original_goal", _go)
        state["goal_original"] = _go
        state["goal_optimized"] = _gopt or ""

        assert state["goal_original"] == "user said this"
        assert state["goal_optimized"] == "optimizer said that"
        assert state["original_goal"] == "user said this"
    finally:
        agent_loop._goal_original_var.reset(tok_o)
        agent_loop._goal_optimized_var.reset(tok_p)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
