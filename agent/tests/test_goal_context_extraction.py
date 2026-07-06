"""BL-121: goal contextvars live in a shared module; services don't import agent_loop privates."""
from __future__ import annotations

import re
from pathlib import Path

_AGENT = Path(__file__).resolve().parent.parent


def test_shared_module_defines_goal_vars():
    from services.agent import goal_context as gc
    gc._goal_original_var.set("hello")
    gc._goal_optimized_var.set("hello, optimized")
    assert gc.get_last_goal_original() == "hello"
    assert gc.get_last_goal_optimized() == "hello, optimized"


def test_agent_loop_reexports_for_backcompat():
    import agent_loop

    # back-compat: the old import path still resolves the same objects
    from services.agent.goal_context import _goal_original_var
    assert agent_loop._goal_original_var is _goal_original_var
    assert callable(agent_loop.get_last_goal_original)


def test_no_service_imports_agent_loop_goal_privates():
    offenders = []
    pat = re.compile(r"from agent_loop import[^\n]*_goal_(original|optimized)_var")
    for py in (_AGENT / "services").rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        if pat.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(_AGENT)))
    assert offenders == [], f"services still import agent_loop goal privates: {offenders}"
