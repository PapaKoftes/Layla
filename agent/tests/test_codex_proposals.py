from __future__ import annotations

import json
from pathlib import Path


def test_codex_proposals_generate_approve(tmp_path, monkeypatch):
    # Use temp "workspace" and allow sandbox check by pointing sandbox root there if used.
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".layla").mkdir()

    from services.relationship_codex import approve_proposal, generate_proposals, list_proposals, load_codex

    generate_proposals(ws, goal_or_context="Talked to Alice about build.", recent_actions="")
    props = list_proposals(ws)["proposals"]
    assert props
    pid = props[0]["id"]
    assert approve_proposal(ws, pid)["ok"] is True
    data = load_codex(ws)
    assert "alice" in (data.get("entities") or {})


def test_plan_report_written_on_done(tmp_path, monkeypatch):
    ws = tmp_path / "ws2"
    ws.mkdir()
    # Ensure this temp workspace is considered sandboxed for plan_service.
    from layla.tools.sandbox_core import set_effective_sandbox
    set_effective_sandbox(str(tmp_path))

    # Create a minimal file-backed plan under .layla_plans using existing plan_service.
    from services.plan_schema import Plan, PlanStep
    from services.plan_service import save_plan

    pid = "p1"
    plan = Plan(id=pid, goal="g", status="approved", steps=[PlanStep(title="t1", status="done")])
    ok, err = save_plan(str(ws), plan)
    assert ok, err
    # simulate done callback
    from services.engine_plans import _write_plan_completion_report
    _write_plan_completion_report(workspace_root=str(ws), file_plan_id=pid, result={"response": "ok"}, started_at=0.0)
    out_dir = ws / ".layla" / "plan_reports"
    assert out_dir.exists()
    files = list(out_dir.glob("p1_*.md"))
    assert files
    txt = files[0].read_text(encoding="utf-8")
    assert "## Steps" in txt

