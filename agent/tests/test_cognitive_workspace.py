"""
Tests for cognitive_workspace: should_use_cognitive_workspace, run_deliberation.
Run from agent/: pytest tests/test_cognitive_workspace.py -v
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import pytest  # noqa: E402


def test_should_use_cognitive_workspace_short_goal():
    from services.cognitive_workspace import should_use_cognitive_workspace
    assert should_use_cognitive_workspace("hi", cfg={}) is False
    assert should_use_cognitive_workspace("x" * 100, cfg={}) is False


def test_should_use_cognitive_workspace_disabled():
    from services.cognitive_workspace import should_use_cognitive_workspace
    goal = "analyze the codebase architecture and figure out why the complex refactor is failing"  # 120+ chars
    assert should_use_cognitive_workspace(goal, cfg={"enable_cognitive_workspace": False}) is False


def test_should_use_cognitive_workspace_complex_goal():
    from services.cognitive_workspace import should_use_cognitive_workspace
    goal = (
        "analyze the codebase architecture and figure out why the complex refactor is failing. "
        "I need to understand the design patterns and debug the authentication flow."
    )
    assert len(goal) >= 120
    assert should_use_cognitive_workspace(goal, cfg={}) is True


def test_should_use_cognitive_workspace_respects_plan_depth():
    from services.cognitive_workspace import should_use_cognitive_workspace
    goal = "debug the complicated authentication flow and investigate why tokens expire"
    assert should_use_cognitive_workspace(goal, cfg={"max_plan_depth": 3}, plan_depth=3) is False


def test_run_deliberation_empty_goal():
    from services.cognitive_workspace import run_deliberation
    result = run_deliberation("")
    assert result["chosen_key"] == "reasoning"
    assert "strategy_hint" in result
    assert result["approaches"] == []


def test_run_deliberation_returns_structure(monkeypatch):
    """run_deliberation returns chosen_key, rationale, strategy_hint, approaches."""
    from services import cognitive_workspace
    from services import llm_gateway

    def mock_generate(*a, **k):
        return {"choices": [{"message": {"content": '{"approaches":[{"id":"A","name":"Search-first","brief":"gather","key":"search"},{"id":"B","name":"Reasoning-first","brief":"think","key":"reasoning"},{"id":"C","name":"Tool-first","brief":"explore","key":"tools"}]}'}}]}

    def mock_eval(*a, **k):
        return {"choices": [{"message": {"content": '{"chosen":"A","rationale":"Need context first"}'}}]}

    calls = []
    def counting_mock(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return mock_generate(*a, **k)
        return mock_eval(*a, **k)

    monkeypatch.setattr(llm_gateway, "run_completion", counting_mock)

    result = cognitive_workspace.run_deliberation(
        "analyze the codebase and debug the complex authentication flow"
    )
    assert "chosen_key" in result
    assert result["chosen_key"] in ("search", "reasoning", "tools")
    assert "chosen_name" in result
    assert "rationale" in result
    assert "strategy_hint" in result
    assert len(result["strategy_hint"]) > 0
    assert "approaches" in result


def test_run_deliberation_fallback_without_llm(monkeypatch):
    """When LLM fails, fallback returns canonical approaches and reasoning-first."""
    from services import cognitive_workspace
    from services import llm_gateway

    monkeypatch.setattr(llm_gateway, "run_completion", lambda *a, **k: {"choices": [{}]})

    result = cognitive_workspace.run_deliberation("debug the complicated flow")
    assert result["chosen_key"] == "reasoning"
    assert "strategy_hint" in result
    assert len(result["approaches"]) >= 2
