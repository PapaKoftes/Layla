"""Task profile + budget envelope (adaptive execution budget)."""
from __future__ import annotations

from types import SimpleNamespace

from services.plan_step_governance import validate_step_outcome
from services.task_budget import allocate_budget, profile_task


def test_profile_short_greeting_low_complexity():
    p = profile_task("hi", "", reasoning_mode="none", research_mode=False, allow_write=False, allow_run=False)
    assert p.base_reasoning == "none"
    assert p.length_bin == "short"
    assert p.complexity_score < 0.5


def test_profile_long_code_goal_higher_complexity():
    goal = "implement a refactor across the repo " + ("def foo(): pass\n" * 20)
    p = profile_task(goal, "", reasoning_mode="deep", research_mode=False, allow_write=True, allow_run=False)
    assert p.base_reasoning == "deep"
    assert p.length_bin == "long"
    assert p.coding_likelihood >= 0.5


def test_research_mode_forces_deep_envelope():
    cfg = {"max_tool_calls": 20, "max_plan_depth": 3, "research_max_tool_calls": 25, "chat_lite_mode": False}
    p = profile_task("x", "", reasoning_mode="none", research_mode=True, allow_write=False, allow_run=False)
    e = allocate_budget(p, cfg)
    assert e.reasoning_mode_effective == "deep"
    assert e.retrieval_depth == "deep"
    assert e.max_tool_calls_effective == 25


def test_none_mode_tight_cap():
    cfg = {"max_tool_calls": 20, "max_plan_depth": 3, "chat_lite_mode": False}
    p = profile_task("ok", "", reasoning_mode="none", research_mode=False, allow_write=False, allow_run=False)
    e = allocate_budget(p, cfg)
    assert e.max_plan_depth_effective == 0
    assert e.macro_planning_allowed is False
    assert e.retrieval_depth == "minimal"


def test_validate_step_success_criteria_substring():
    step = SimpleNamespace(
        type="analysis",
        id="1",
        tools=[],
        tools_auto_filled=False,
        validation_hint="",
        success_criteria="substring:pytest",
    )
    ok, _ = validate_step_outcome(
        step,
        {"ok": True, "refused": False, "response": "", "state": {"steps": [{"action": "reason", "result": "tests ran pytest ok"}]}},
    )
    assert ok is True


def test_validate_step_success_criteria_fails():
    step = SimpleNamespace(
        type="analysis",
        id="1",
        tools=[],
        tools_auto_filled=False,
        validation_hint="",
        success_criteria="substring:EXPECTED_MARKER_XYZ",
    )
    ok, reason = validate_step_outcome(
        step,
        {"ok": True, "refused": False, "response": "done but wrong content", "state": {"steps": []}},
    )
    assert ok is False
    assert "success_criteria" in reason
