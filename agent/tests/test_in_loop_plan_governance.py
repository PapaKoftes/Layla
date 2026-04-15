"""In-loop should_plan → create_plan → execute_plan governance parity (config-gated)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture
def _patch_reasoning_light(monkeypatch):
    monkeypatch.setattr("services.reasoning_classifier.classify_reasoning_need", lambda *a, **k: "light")
    monkeypatch.setattr("services.reasoning_classifier.stabilize_reasoning_mode", lambda _p, c: c)


def test_in_loop_execute_plan_passes_governance_when_enabled(monkeypatch, _patch_reasoning_light):
    import agent_loop
    import runtime_safety

    kw_captured: dict = {}

    def fake_execute_plan(
        plan,
        agent_run_fn,
        goal_prefix="",
        plan_depth=0,
        *,
        step_governance=False,
        default_max_retries=1,
        cfg=None,
        **kwargs,
    ):
        kw_captured.clear()
        kw_captured.update(kwargs)
        kw_captured["step_governance"] = step_governance
        kw_captured["default_max_retries"] = default_max_retries
        return {
            "status": "plan_completed",
            "steps_done": [{"step": 1, "task": "x", "result_status": "ok", "governance_ok": True}],
            "summary": "ok",
            "all_steps_ok": True,
        }

    _orig_load = runtime_safety.load_config

    def _load_gov_on():
        d = dict(_orig_load())
        d["in_loop_plan_governance_enabled"] = True
        d["in_loop_plan_default_max_retries"] = 2
        d["planning_strict_mode"] = True
        d["engineering_pipeline_enabled"] = False
        d["max_runtime_seconds"] = max(int(d.get("max_runtime_seconds", 900) or 900), 180)
        d["max_tool_calls"] = max(int(d.get("max_tool_calls", 5) or 5), 12)
        return d

    monkeypatch.setattr(runtime_safety, "load_config", _load_gov_on)
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda **k: False)
    monkeypatch.setattr("services.planner.should_plan", lambda *a, **k: True)
    monkeypatch.setattr(
        "services.planner.create_plan",
        lambda goal, max_steps=6, cfg=None, prior_plans_digest="", **kwargs: [
            {"step": 1, "task": "analyze and refactor the module", "tools": [], "role": ""}
        ],
    )
    monkeypatch.setattr("services.planner.execute_plan_with_optional_graph", fake_execute_plan)

    out = agent_loop.autonomous_run(
        "analyze and refactor the module with a full implementation plan " + ("x" * 80),
        context="",
        workspace_root=str(AGENT_DIR),
        allow_write=True,
        allow_run=False,
        conversation_history=[],
        aspect_id="morrigan",
        plan_approved=False,
    )
    assert out.get("status") == "plan_completed"
    assert out.get("all_steps_ok") is True
    assert kw_captured.get("step_governance") is True
    assert kw_captured.get("default_max_retries") == 2
    assert kw_captured.get("plan_approved") is True


def test_in_loop_execute_plan_nested_plan_approved_false_when_read_only(monkeypatch, _patch_reasoning_light):
    import agent_loop
    import runtime_safety

    kw_captured: dict = {}

    def fake_execute_plan(
        plan,
        agent_run_fn,
        goal_prefix="",
        plan_depth=0,
        *,
        step_governance=False,
        default_max_retries=1,
        cfg=None,
        **kwargs,
    ):
        kw_captured.clear()
        kw_captured.update(kwargs)
        kw_captured["step_governance"] = step_governance
        kw_captured["default_max_retries"] = default_max_retries
        return {
            "status": "plan_completed",
            "steps_done": [],
            "summary": "ok",
            "all_steps_ok": True,
        }

    _orig_load = runtime_safety.load_config

    def _load_gov_on():
        d = dict(_orig_load())
        d["in_loop_plan_governance_enabled"] = True
        d["in_loop_plan_default_max_retries"] = 1
        d["planning_strict_mode"] = True
        d["engineering_pipeline_enabled"] = False
        d["max_runtime_seconds"] = max(int(d.get("max_runtime_seconds", 900) or 900), 180)
        d["max_tool_calls"] = max(int(d.get("max_tool_calls", 5) or 5), 12)
        return d

    monkeypatch.setattr(runtime_safety, "load_config", _load_gov_on)
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda **k: False)
    monkeypatch.setattr("services.planner.should_plan", lambda *a, **k: True)
    monkeypatch.setattr(
        "services.planner.create_plan",
        lambda goal, max_steps=6, cfg=None, prior_plans_digest="", **kwargs: [
            {"step": 1, "task": "analyze the repository", "tools": [], "role": ""}
        ],
    )
    monkeypatch.setattr("services.planner.execute_plan_with_optional_graph", fake_execute_plan)

    agent_loop.autonomous_run(
        "analyze the repository and document findings " + ("y" * 80),
        workspace_root=str(AGENT_DIR),
        allow_write=False,
        allow_run=False,
        plan_approved=False,
    )
    assert kw_captured.get("step_governance") is True
    assert kw_captured.get("plan_approved") is False


def test_in_loop_execute_plan_legacy_no_step_governance_when_disabled(monkeypatch, _patch_reasoning_light):
    import agent_loop
    import runtime_safety

    kw_captured: dict = {}

    def fake_execute_plan(
        plan,
        agent_run_fn,
        goal_prefix="",
        plan_depth=0,
        *,
        step_governance=False,
        default_max_retries=1,
        cfg=None,
        **kwargs,
    ):
        kw_captured.clear()
        kw_captured.update(kwargs)
        kw_captured["step_governance"] = step_governance
        kw_captured["default_max_retries"] = default_max_retries
        return {"status": "plan_completed", "steps_done": [], "summary": "ok"}

    _orig_load = runtime_safety.load_config

    def _load_gov_off():
        d = dict(_orig_load())
        d["in_loop_plan_governance_enabled"] = False
        d["engineering_pipeline_enabled"] = False
        d["max_runtime_seconds"] = max(int(d.get("max_runtime_seconds", 900) or 900), 180)
        d["max_tool_calls"] = max(int(d.get("max_tool_calls", 5) or 5), 12)
        return d

    monkeypatch.setattr(runtime_safety, "load_config", _load_gov_off)
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda **k: False)
    monkeypatch.setattr("services.planner.should_plan", lambda *a, **k: True)
    monkeypatch.setattr(
        "services.planner.create_plan",
        lambda goal, max_steps=6, cfg=None, prior_plans_digest="", **kwargs: [
            {"step": 1, "task": "build something", "tools": [], "role": ""}
        ],
    )
    monkeypatch.setattr("services.planner.execute_plan_with_optional_graph", fake_execute_plan)

    out = agent_loop.autonomous_run(
        "build something substantial with multiple phases " + ("z" * 80),
        workspace_root=str(AGENT_DIR),
        allow_write=False,
        allow_run=False,
    )
    assert out.get("status") == "plan_completed"
    assert "all_steps_ok" not in out
    assert kw_captured.get("step_governance") is not True
