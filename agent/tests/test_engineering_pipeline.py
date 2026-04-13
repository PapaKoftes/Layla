"""Engineering pipeline: clarifier block, planning lock, orchestration stubs."""
from __future__ import annotations

import pytest


def test_engineering_planning_locked_default_false():
    from services.engineering_pipeline import engineering_planning_locked, lock_engineering_planning, unlock_engineering_planning

    assert engineering_planning_locked() is False
    tok = lock_engineering_planning()
    assert engineering_planning_locked() is True
    unlock_engineering_planning(tok)
    assert engineering_planning_locked() is False


def test_run_clarifier_needs_input_blocks_planner(monkeypatch):
    from services import engineering_pipeline as ep

    monkeypatch.setattr(ep, "run_clarifier", lambda *a, **k: {"status": "needs_input", "questions": ["Which file?"]})
    calls: list[str] = []

    def _no_plan(*a, **k):
        calls.append("create_plan")
        return []

    monkeypatch.setattr("services.planner.create_plan", _no_plan)

    out = ep.run_execute_pipeline(
        goal="fix it",
        context="",
        workspace_root="",
        allow_write=False,
        allow_run=False,
        conversation_history=[],
        aspect_id="morrigan",
        show_thinking=False,
        stream_final=False,
        ux_state_queue=None,
        research_mode=False,
        plan_depth=0,
        persona_focus="",
        conversation_id="t1",
        cognition_workspace_roots=None,
        client_abort_event=None,
        background_progress_callback=None,
        clarification_reply="",
        cfg={},
        agent_run_fn=lambda **kw: {"status": "finished", "steps": [{"action": "reason", "result": "x"}]},
        memory_influenced=[],
        active_aspect={"id": "morrigan", "name": "Morrigan"},
    )
    assert out.get("status") == "pipeline_needs_input"
    assert "Which file?" in (out.get("questions") or [])
    assert calls == []


def test_autonomous_run_signature_has_pipeline_params():
    import inspect

    from agent_loop import autonomous_run

    sig = inspect.signature(autonomous_run)
    assert "skip_engineering_pipeline" in sig.parameters
    assert "engineering_pipeline_mode" in sig.parameters
    assert "clarification_reply" in sig.parameters


def test_planner_kw_includes_skip_engineering_pipeline():
    from services.planner import _AUTONOMOUS_KW_KEYS

    assert "skip_engineering_pipeline" in _AUTONOMOUS_KW_KEYS
