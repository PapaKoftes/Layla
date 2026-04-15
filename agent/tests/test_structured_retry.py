from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_structured_retry_ladder_injects_goal_and_model_override(monkeypatch) -> None:
    """
    Validate in-loop structured retry ladder:
    - attempt 2 injects previous failure summary + "Fix ONLY"
    - attempt 3 injects simplify instructions + passes model_override to nested execution
    """
    import runtime_safety

    # Force planning path + governance retry behavior.
    cfg: dict[str, Any] = {
        "planning_enabled": True,
        "structured_retry_enabled": True,
        "structured_retry_max_levels": 3,
        "in_loop_plan_governance_enabled": True,
        "pipeline_enforcement_enabled": True,
        "tool_routing_enabled": True,
        "completion_gate_enabled": False,
        # Ensure attempt 3 sets model_override="coding"
        "coding_model": "dummy-coder",
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)

    # Ensure should_plan always returns True.
    import services.planner as planner

    monkeypatch.setattr(planner, "should_plan", lambda *_a, **_k: True)

    create_plan_goals: list[str] = []

    def _fake_create_plan(goal: str, **_kwargs):
        create_plan_goals.append(goal)
        # Minimal valid plan. Validation will run and pass.
        return [{"step": 1, "task": "Inspect", "tools": ["read_file"]}]

    monkeypatch.setattr(planner, "create_plan", _fake_create_plan)

    exec_kwargs_seen: list[dict[str, Any]] = []

    def _fake_execute_plan_with_optional_graph(plan, autonomous_run, **kwargs):
        exec_kwargs_seen.append(dict(kwargs))
        n = len(exec_kwargs_seen)
        if n in (1, 2):
            # Trigger mandatory debug→retry in agent_loop.
            return {"all_steps_ok": False, "summary": f"fail{n}", "steps_done": []}
        return {"all_steps_ok": True, "summary": "ok", "steps_done": []}

    monkeypatch.setattr(planner, "execute_plan_with_optional_graph", _fake_execute_plan_with_optional_graph)

    import agent_loop
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda *_a, **_k: False)

    # Call the internal impl directly to avoid global scheduling returning system_busy
    # when the full suite is running.
    out = agent_loop._autonomous_run_impl(
        "Do something non-trivial that requires a plan.",
        "",
        "",
        False,
        False,
        [],
        "",
        False,
        False,
        None,
        False,
    )

    assert out["status"] == "plan_completed"
    assert len(create_plan_goals) >= 3
    assert "[Retry 1: Previous attempt failed. Fix ONLY the reported failure.]" in create_plan_goals[1]
    assert "[Last plan execution summary]:" in create_plan_goals[1]
    assert "fail1" in create_plan_goals[1]
    assert "[Retry 2/3: Simplify. Use at most 3 steps. Minimal viable solution only.]" in create_plan_goals[2]

    # attempt 3 should pass model_override="coding" into nested execution kwargs.
    assert len(exec_kwargs_seen) >= 3
    assert exec_kwargs_seen[0].get("model_override") is None
    assert exec_kwargs_seen[1].get("model_override") is None
    assert exec_kwargs_seen[2].get("model_override") == "coding"

