"""
Golden HTTP flow: POST /agent (tool → approval_required) → POST /approve → POST /agent (reason).
Mocks LLM at decision + completion boundaries only; exercises real agent_loop + approvals wiring.

Run from agent/: pytest tests/test_golden_flow_http.py -v
"""
from __future__ import annotations

import sys
import uuid as uuid_mod
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture()
def golden_pending_store(monkeypatch):
    """In-memory pending list shared by agent_loop._write_pending and approvals router."""
    import main as _main_loaded  # noqa: F401 — triggers set_refs; must patch after this

    pending: list = []

    def _mem_write_pending(tool: str, args: dict) -> str:
        from layla.time_utils import utcnow
        from layla.tools.registry import TOOLS

        eid = str(uuid_mod.uuid4())
        risk = (TOOLS.get(tool) or {}).get("risk_level") or "medium"
        pending.append(
            {
                "id": eid,
                "tool": tool,
                "args": dict(args),
                "requested_at": utcnow().isoformat(),
                "status": "pending",
                "risk_level": risk,
            }
        )
        return eid

    def _read():
        return list(pending)

    def _write(new_list: list) -> None:
        pending[:] = new_list

    import agent_loop
    import shared_state

    monkeypatch.setattr(agent_loop, "_write_pending", _mem_write_pending)
    monkeypatch.setattr(shared_state, "_read_pending", _read)
    monkeypatch.setattr(shared_state, "_write_pending_list", _write)
    monkeypatch.setattr(shared_state, "_audit_fn", lambda *a, **k: None)

    return pending


def test_golden_chat_tool_approve_then_reason(tmp_path, monkeypatch, golden_pending_store):
    """write_file without allow_write → pending → approve executes → follow-up /agent returns completion text."""
    from fastapi.testclient import TestClient

    import agent_loop
    import layla.memory.distill as distill_mod
    import layla.tools.impl.file_ops as file_ops_mod
    import layla.tools.registry as tools_registry
    import routers.agent as agent_router
    import runtime_safety
    import services.coordinator as coordinator_mod
    import services.tool_policy as tool_policy
    from main import app
    from services import model_router, planner

    target = tmp_path / "golden_e2e.txt"
    # Path must contain ":" or "\\" for _extract_file_and_content
    path_token = str(target.resolve())

    # Each POST /agent starts a fresh autonomous_run with empty steps — use phase, not steps.
    decision_phase = {"post_index": 0}

    def fake_llm_decision(_goal, _state, _context, _active_aspect, _show_thinking, _history):
        if decision_phase["post_index"] == 0:
            return {"action": "tool", "tool": "write_file"}
        return {"action": "reason", "objective_complete": True}

    def fake_run_completion(*_a, **_kw):
        # Must be long enough to satisfy completion gate heuristics in production code paths.
        return (
            "E2E final answer.\n\n"
            "This is a longer completion payload used by the golden-flow HTTP test to avoid triggering "
            "the completion quality gate for being too short."
        )

    monkeypatch.setattr(agent_loop, "_llm_decision", fake_llm_decision)
    monkeypatch.setattr(agent_loop, "run_completion", fake_run_completion)
    monkeypatch.setattr(runtime_safety, "require_approval", lambda _tool: True)
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda **_kw: False)
    monkeypatch.setattr(tool_policy, "tool_allowed", lambda _intent, _vt: True)
    # Avoid Chroma/embedder work during autonomous_run (keeps test fast + deterministic).
    monkeypatch.setattr(agent_loop, "_semantic_recall", lambda *_a, **_k: "")
    monkeypatch.setattr(agent_loop, "_load_learnings", lambda *_a, **_k: "")
    monkeypatch.setattr(model_router, "is_routing_enabled", lambda *a, **k: False)
    monkeypatch.setattr(planner, "should_plan", lambda *a, **k: False)
    _real_build_trace = coordinator_mod.build_coordinator_trace

    def _trace_no_force_plan(goal: str, context: str, cfg: dict, **kw):
        t = dict(_real_build_trace(goal, context, cfg, **kw))
        t["complexity_score"] = min(float(t.get("complexity_score") or 0), 0.2)
        return t

    monkeypatch.setattr(coordinator_mod, "build_coordinator_trace", _trace_no_force_plan)
    monkeypatch.setattr(distill_mod, "run_distill_after_outcome", lambda *a, **k: None)
    monkeypatch.setattr(tools_registry, "inside_sandbox", lambda _p: True)
    # Approvals call TOOLS fn directly; file_ops binds sandbox_core.inside_sandbox at import time.
    monkeypatch.setattr(file_ops_mod, "inside_sandbox", lambda _p: True)
    monkeypatch.setattr(agent_router, "_model_ready_message", lambda: None)

    client = TestClient(app)
    conv_id = str(uuid_mod.uuid4())
    goal = f"Write path {path_token} with content golden_line_content"

    r1 = client.post(
        "/agent",
        json={
            "message": goal,
            "workspace_root": str(tmp_path),
            "allow_write": False,
            "allow_run": False,
            "conversation_id": conv_id,
        },
    )
    decision_phase["post_index"] = 1
    assert r1.status_code == 200
    data1 = r1.json()
    steps = (data1.get("state") or {}).get("steps") or []
    wf = next((s for s in steps if s.get("action") == "write_file"), None)
    assert wf is not None
    res = wf.get("result") or {}
    assert res.get("reason") == "approval_required"
    approval_id = res.get("approval_id")
    assert approval_id

    r_approve = client.post("/approve", json={"id": approval_id})
    assert r_approve.status_code == 200
    assert r_approve.json().get("ok") is True
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "golden_line_content"

    r2 = client.post(
        "/agent",
        json={
            "message": "Summarize what happened in one sentence.",
            "workspace_root": str(tmp_path),
            "allow_write": False,
            "allow_run": False,
            "conversation_id": conv_id,
        },
    )
    assert r2.status_code == 200
    assert "E2E final answer." in (r2.json().get("response") or "")

    from layla.memory.db import get_conversation_messages

    msgs = get_conversation_messages(conv_id, limit=20)
    roles = [m.get("role") for m in msgs]
    assert "user" in roles and "assistant" in roles
