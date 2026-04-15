"""execute_plan_with_optional_graph: graph-only execution invariants."""
from __future__ import annotations


def test_optional_graph_hard_fails_when_disabled():
    from services import planner as pl

    calls: list[str] = []

    def fake_run(step_goal: str, **kw: object) -> dict:
        calls.append(step_goal[:24])
        return {"status": "finished", "steps": []}

    plan = [
        {"step": 1, "task": "first step", "tools": [], "role": ""},
        {"step": 2, "task": "second step", "tools": [], "role": ""},
    ]
    cfg = {"coordinator_graph_execution_enabled": False, "max_plan_depth": 3}
    try:
        _ = pl.execute_plan_with_optional_graph(plan, fake_run, cfg=cfg, workspace_root=".")
        assert False, "expected graph_execution_disabled"
    except RuntimeError as e:
        assert "graph_execution_disabled" in str(e)
    assert len(calls) == 0


def test_optional_graph_runs_for_single_step_when_enabled(monkeypatch):
    from services import planner as pl

    seen: list[dict] = []

    def fake_graph(*, plan_steps, step_runner, cfg):
        assert cfg.get("coordinator_graph_execution_enabled") is True
        assert len(plan_steps) == 1
        r = step_runner({"step": plan_steps[0]["id"], "task": plan_steps[0]["task"], "tools": []})
        seen.append(r)
        return {"ok": True, "results": [r]}

    monkeypatch.setattr("services.coordinator.run_with_plan_graph", fake_graph)

    def fake_run(step_goal: str, **kw: object) -> dict:
        return {"status": "finished", "steps": []}

    plan = [{"step": 1, "task": "only step", "tools": [], "role": ""}]
    cfg = {"coordinator_graph_execution_enabled": True, "max_plan_depth": 3}
    out = pl.execute_plan_with_optional_graph(plan, fake_run, cfg=cfg, workspace_root=".")
    assert out.get("status") == "plan_completed"
    assert len(seen) == 1


def test_optional_graph_hard_fails_on_graph_error(monkeypatch):
    from services import planner as pl

    def fake_graph(*, plan_steps, step_runner, cfg):
        return {"ok": False, "reason": "boom", "results": []}

    monkeypatch.setattr("services.coordinator.run_with_plan_graph", fake_graph)

    calls: list[str] = []

    def fake_run(step_goal: str, **kw: object) -> dict:
        calls.append(step_goal)
        return {"status": "finished", "steps": []}

    plan = [{"step": 1, "task": "t1", "tools": [], "role": ""}]
    cfg = {"coordinator_graph_execution_enabled": True, "max_plan_depth": 3}
    try:
        _ = pl.execute_plan_with_optional_graph(plan, fake_run, cfg=cfg, workspace_root=".")
        assert False, "expected graph_execution_failed"
    except RuntimeError as e:
        assert "graph_execution_failed" in str(e)
    assert len(calls) == 0
