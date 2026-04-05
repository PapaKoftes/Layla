"""plan_step_governance: validation, confidence, approve-time checks."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_validate_file_plan_rejects_bad_dep():
    from services.plan_schema import Plan, PlanStep
    from services.plan_step_governance import validate_file_plan_before_approval

    a = PlanStep(id="a", title="a", description="d")
    b = PlanStep(id="b", title="b", description="d2", depends_on=["missing"])
    errs = validate_file_plan_before_approval(Plan(goal="g", steps=[a, b]))
    assert any("unknown_dependency" in e for e in errs)


def test_validate_file_plan_rejects_unknown_tool():
    from services.plan_schema import Plan, PlanStep
    from services.plan_step_governance import validate_file_plan_before_approval

    s = PlanStep(id="x", title="t", description="d", tools=["__not_a_real_tool_xyz__"])
    errs = validate_file_plan_before_approval(Plan(goal="g", steps=[s]))
    assert any("unknown_tool" in e for e in errs)


def test_validate_step_edit_requires_patch_signal():
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="e", description="edit", type="edit")
    ok, reason = validate_step_outcome(
        step,
        {"response": "I edited the file conceptually.", "state": {"steps": []}},
    )
    assert ok is False
    assert "edit_step" in reason


def test_low_confidence_hedge():
    from services.plan_step_governance import low_confidence_response

    assert low_confidence_response({"response": "I'm not sure this is correct.", "refused": False})


def test_validate_step_edit_accepts_changed():
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="e", description="edit", type="edit")
    ok, _reason = validate_step_outcome(
        step,
        {
            "response": "File changed as requested.",
            "state": {"steps": []},
        },
    )
    assert ok is True


def test_validate_step_test_passed():
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="t", description="run tests", type="test")
    ok, _reason = validate_step_outcome(
        step,
        {
            "response": "All tests passed.",
            "state": {"steps": [{"action": "run_tests", "result": {"ok": True, "stdout": "passed"}}]},
        },
    )
    assert ok is True


def test_validate_step_rejects_fatal_traceback_phrase():
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="a", description="d", type="analysis")
    ok, reason = validate_step_outcome(
        step,
        {"response": "Traceback (most recent call last):\n  File x", "state": {"steps": []}},
    )
    assert ok is False
    assert "fatal" in reason


def test_validate_step_requires_listed_tool_invocation():
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="a", description="read src", type="analysis", tools=["read_file"])
    ok, reason = validate_step_outcome(
        step,
        {"response": "I read it mentally.", "state": {"steps": []}},
    )
    assert ok is False
    assert "tool" in reason.lower()


@pytest.mark.parametrize(
    "step_type,payload,expect_ok,reason_needle",
    [
        ("edit", {"response": "Unified diff apply_patch applied successfully.", "state": {"steps": []}}, True, ""),
        ("edit", {"response": "Thought about editing only.", "state": {"steps": []}}, False, "edit_step"),
        (
            "edit",
            {
                "response": "Wrote file.",
                "state": {"steps": [{"action": "write_file", "result": {"ok": True}}]},
            },
            True,
            "",
        ),
        (
            "edit",
            {
                "response": "Inspected only.",
                "state": {"steps": [{"action": "read_file", "result": {"ok": True}}]},
            },
            False,
            "no_successful_write_tool_trace",
        ),
        ("test", {"response": "All tests passed.", "state": {"steps": []}}, True, ""),
        ("test", {"response": "Executed checks.", "state": {"steps": []}}, False, "test_step"),
        (
            "test",
            {
                "response": "Green.",
                "state": {"steps": [{"action": "run_tests", "result": {"ok": True}}]},
            },
            True,
            "",
        ),
        (
            "test",
            {
                "response": "Pytest output.",
                "state": {"steps": [{"action": "run_tests", "result": {"ok": False}}]},
            },
            False,
            "tool:run_tests",
        ),
    ],
)
def test_validate_step_outcome_golden_matrix(step_type, payload, expect_ok, reason_needle):
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="x", description="d", type=step_type)
    ok, reason = validate_step_outcome(step, payload)
    assert ok is expect_ok
    if reason_needle:
        assert reason_needle in (reason or "")


def test_validate_file_plan_rejects_mutating_empty_tools_when_flag(monkeypatch):
    from services.plan_schema import Plan, PlanStep
    from services.plan_step_governance import validate_file_plan_before_approval

    monkeypatch.setattr(
        "services.plan_step_governance._plan_governance_require_nonempty_tools",
        lambda: True,
    )
    s = PlanStep(id="e1", title="e", description="edit something", type="edit", tools=[])
    errs = validate_file_plan_before_approval(Plan(goal="g", steps=[s]))
    assert any("step_missing_tools" in e for e in errs)


def test_validate_sqlite_plan_rejects_mutating_empty_tools_when_flag(monkeypatch):
    from services.plan_step_governance import validate_sqlite_plan_before_approval

    monkeypatch.setattr(
        "services.plan_step_governance._plan_governance_require_nonempty_tools",
        lambda: True,
    )
    plan = {
        "steps": [
            {"id": 1, "type": "build", "description": "compile", "status": "pending", "tools": []},
        ],
    }
    errs = validate_sqlite_plan_before_approval(plan)
    assert any("missing_tools" in e for e in errs)


def test_normalize_plan_steps_tools_fills_defaults():
    from services import planner as pl

    cfg = {
        "plan_governance_require_nonempty_step_tools": True,
        "plan_step_default_read_tools": ["read_file", "list_dir"],
    }
    plan = [{"step": 1, "task": "inspect", "tools": [], "role": ""}]
    pl.normalize_plan_steps_tools(plan, cfg)
    assert "read_file" in plan[0]["tools"]
    assert "list_dir" in plan[0]["tools"]
    assert plan[0].get("_tools_auto_filled") is True


def test_validate_step_rejects_tools_auto_filled_when_config(monkeypatch):
    from types import SimpleNamespace

    from services.plan_step_governance import validate_step_outcome

    monkeypatch.setattr(
        "services.plan_step_governance._plan_governance_reject_auto_filled",
        lambda: True,
    )
    step = SimpleNamespace(
        type="analysis",
        tools=["read_file"],
        tools_auto_filled=True,
    )
    ok, reason = validate_step_outcome(
        step,
        {"response": "Enough text for confidence.", "refused": False, "state": {"steps": []}},
    )
    assert ok is False
    assert "auto_filled" in reason


def test_normalize_plan_steps_tools_skips_mutating_role():
    from services import planner as pl

    cfg = {"plan_governance_require_nonempty_step_tools": True, "plan_step_default_read_tools": ["read_file"]}
    plan = [{"step": 1, "task": "patch", "tools": [], "role": "edit"}]
    pl.normalize_plan_steps_tools(plan, cfg)
    assert plan[0]["tools"] == []


def test_strict_tool_evidence_write_requires_path(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"plan_governance_strict_tool_evidence": True},
    )
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="e", description="d", type="edit")
    ok, reason = validate_step_outcome(
        step,
        {"response": "done", "state": {"steps": [{"action": "write_file", "result": {"ok": True}}]}},
    )
    assert ok is False
    assert "no_successful_write_tool_trace" in reason


def test_strict_tool_evidence_accepts_write_with_path(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"plan_governance_strict_tool_evidence": True},
    )
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="e", description="d", type="edit")
    ok, _reason = validate_step_outcome(
        step,
        {
            "response": "ok",
            "state": {"steps": [{"action": "write_file", "result": {"ok": True, "path": "/sandbox/foo.py"}}]},
        },
    )
    assert ok is True


def test_strict_tool_evidence_test_rejects_hollow_run_tests(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"plan_governance_strict_tool_evidence": True},
    )
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="t", description="d", type="test")
    ok, reason = validate_step_outcome(
        step,
        {
            "response": "ok",
            "state": {
                "steps": [
                    {
                        "action": "run_tests",
                        "result": {"ok": True, "returncode": 0, "passed": 0, "failed": 0, "output": ""},
                    }
                ]
            },
        },
    )
    assert ok is False
    assert "no_successful_test_tool_trace" in reason


def test_strict_tool_evidence_test_accepts_pytest_output(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"plan_governance_strict_tool_evidence": True},
    )
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="t", description="d", type="test")
    ok, _reason = validate_step_outcome(
        step,
        {
            "response": "ok",
            "state": {
                "steps": [
                    {
                        "action": "run_tests",
                        "result": {
                            "ok": True,
                            "returncode": 0,
                            "passed": 2,
                            "failed": 0,
                            "output": "",
                        },
                    }
                ]
            },
        },
    )
    assert ok is True


def test_strict_requires_tool_traces_not_prose(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"plan_governance_strict_tool_evidence": True},
    )
    from services.plan_schema import PlanStep
    from services.plan_step_governance import validate_step_outcome

    step = PlanStep(title="e", description="d", type="edit")
    ok, reason = validate_step_outcome(
        step,
        {"response": "Unified diff apply_patch applied successfully.", "state": {"steps": []}},
    )
    assert ok is False
    assert "strict:requires_tool_traces" in reason


def test_hard_mode_implies_reject_auto_filled(monkeypatch):
    from types import SimpleNamespace

    import runtime_safety
    from services.plan_step_governance import validate_step_outcome

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"plan_governance_hard_mode": True},
    )
    step = SimpleNamespace(type="analysis", tools=[], tools_auto_filled=True)
    ok, reason = validate_step_outcome(
        step,
        {"response": "Enough text here for confidence heuristics to pass.", "refused": False, "state": {"steps": []}},
    )
    assert ok is False
    assert "auto_filled" in reason


def test_hard_mode_implies_require_nonempty_tools_on_mutating(monkeypatch):
    import runtime_safety
    from services.plan_schema import Plan, PlanStep
    from services.plan_step_governance import validate_file_plan_before_approval

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"plan_governance_hard_mode": True},
    )
    s = PlanStep(id="e1", title="e", description="edit something", type="edit", tools=[])
    errs = validate_file_plan_before_approval(Plan(goal="g", steps=[s]))
    assert any("step_missing_tools" in e for e in errs)
