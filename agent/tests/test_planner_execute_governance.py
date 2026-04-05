"""SQLite-style execute_plan with step_governance=True."""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_execute_plan_governance_success():
    from services import planner as pl

    def fake_run(goal: str, **_kw: object) -> dict:
        return {
            "status": "finished",
            "refused": False,
            "response": "Completed with enough text for confidence checks.",
            "state": {"steps": []},
        }

    plan = [
        {"step": 1, "task": "Analyze", "tools": [], "role": "analysis"},
    ]
    out = pl.execute_plan(plan, fake_run, step_governance=True, default_max_retries=1)
    assert out.get("all_steps_ok") is True
    assert out["steps_done"][0].get("governance_ok") is True


def test_execute_plan_governance_outer_retry_after_validation_fail():
    from services import planner as pl

    calls: list[str] = []

    def fake_run(goal: str, **_kw: object) -> dict:
        calls.append(goal)
        if "Retry" not in goal:
            return {
                "status": "finished",
                "refused": False,
                "response": "Long narrative only; described intent but did not modify any sources.",
                "state": {"steps": []},
            }
        return {
            "status": "finished",
            "refused": False,
            "response": "Used apply_patch successfully.",
            "state": {"steps": []},
        }

    plan = [{"step": 1, "task": "Edit file", "tools": [], "role": "edit", "max_retries": 1}]
    out = pl.execute_plan(plan, fake_run, step_governance=True, default_max_retries=0)
    assert out.get("all_steps_ok") is True
    assert len(calls) == 2


def test_execute_plan_governance_tool_allowlist_blocks():
    from services import planner as pl
    from services.tool_allowlist_context import get_plan_step_tool_allowlist

    seen: list[frozenset[str] | None] = []

    def fake_run(goal: str, **_kw: object) -> dict:
        seen.append(get_plan_step_tool_allowlist())
        return {
            "status": "finished",
            "refused": False,
            "response": "Used read_file as required for this governance test run.",
            "state": {"steps": [{"action": "read_file", "result": {"ok": True}}]},
        }

    plan = [{"step": 1, "task": "Read", "tools": ["read_file"], "role": "analysis"}]
    out = pl.execute_plan(plan, fake_run, step_governance=True)
    assert out.get("all_steps_ok") is True
    assert any(al == frozenset({"read_file"}) for al in seen if al)


def test_execute_plan_governance_edit_requires_write_tool_when_trace_present():
    from services import planner as pl

    def fake_run(goal: str, **_kw: object) -> dict:
        return {
            "status": "finished",
            "refused": False,
            "response": "Inspected the file carefully with read_file.",
            "state": {"steps": [{"action": "read_file", "result": {"ok": True}}]},
        }

    plan = [{"step": 1, "task": "Edit config", "tools": ["read_file", "apply_patch"], "role": "edit"}]
    out = pl.execute_plan(plan, fake_run, step_governance=True, default_max_retries=0)
    assert out.get("all_steps_ok") is False
    assert "no_successful_write_tool_trace" in (out["steps_done"][0].get("validation_error") or "")


def test_execute_plan_legacy_no_governance_no_extra_fields():
    from services import planner as pl

    def fake_run(goal: str, **_kw: object) -> dict:
        return {"status": "ok", "response": "hi"}

    out = pl.execute_plan(
        [{"step": 1, "task": "t", "tools": [], "role": ""}],
        fake_run,
        step_governance=False,
    )
    assert "all_steps_ok" not in out
    assert "governance_ok" not in (out.get("steps_done") or [{}])[0]
