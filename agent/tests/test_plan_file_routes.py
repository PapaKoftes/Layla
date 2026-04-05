"""File-backed `/plan/*` API (`.layla_plans/`) — separate from SQLite `/plans`."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    base = tmp_path.resolve()

    def _sandbox_ok(p: Path) -> bool:
        try:
            p.resolve().relative_to(base)
            return p.is_dir()
        except ValueError:
            return False

    import services.plan_service as plan_service_mod

    monkeypatch.setattr(plan_service_mod, "inside_sandbox", _sandbox_ok)

    def fake_run(*_a, **_k):
        return {
            "response": "Completed the step with a clear summary for governance validation.",
            "refused": False,
            "state": {"status": "finished", "steps": []},
        }

    monkeypatch.setattr("agent_loop.autonomous_run", fake_run)

    from main import app

    return TestClient(app), root


def test_plan_file_create_get_approve_add_steps_execute(client):
    tc, root = client
    r = tc.post("/plan/create", json={"workspace_root": str(root), "goal": "improve repo", "context": "ctx"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    pid = j["plan"]["id"]
    assert (root / ".layla_plans" / f"{pid}.json").is_file()

    r0 = tc.get(f"/plan/{pid}", params={"workspace_root": str(root)})
    assert r0.status_code == 200
    assert r0.json()["plan"]["status"] == "draft"

    r1 = tc.post(f"/plan/{pid}/add_steps", params={"workspace_root": str(root)}, json={"steps": [{"title": "t1", "description": "d1", "type": "analysis"}]})
    assert r1.status_code == 200
    assert len(r1.json()["plan"]["steps"]) == 1

    r2 = tc.post(f"/plan/{pid}/approve", params={"workspace_root": str(root)})
    assert r2.status_code == 200
    assert r2.json()["plan"]["status"] == "approved"

    r3 = tc.post(f"/plan/{pid}/execute_next", params={"workspace_root": str(root)})
    assert r3.status_code == 200
    body = r3.json()
    assert body.get("ok") is True
    assert body.get("step_id")


def test_plan_file_run_continuous_rejects_subprocess_workers(client, monkeypatch):
    tc, root = client
    import runtime_safety as rs

    _real = rs.load_config

    def _cfg() -> dict:
        d = dict(_real())
        d["background_use_subprocess_workers"] = True
        return d

    monkeypatch.setattr(rs, "load_config", _cfg)
    r = tc.post("/plan/create", json={"workspace_root": str(root), "goal": "g"})
    pid = r.json()["plan"]["id"]
    tc.post(
        f"/plan/{pid}/add_steps",
        params={"workspace_root": str(root)},
        json={"steps": [{"title": "s", "description": "do work", "type": "analysis"}]},
    )
    tc.post(f"/plan/{pid}/approve", params={"workspace_root": str(root)})
    r2 = tc.post(
        f"/plan/{pid}/run_continuous",
        params={"workspace_root": str(root)},
        json={},
    )
    assert r2.status_code == 400
    assert r2.json().get("error") == "file_plan_continuous_requires_thread_workers"


def test_summarize_memory_helpers():
    from services import project_memory as pm

    assert "0 files" in pm.summarize_memory(None)
    doc = pm.empty_document("/x")
    doc["files"] = {"a.py": {}}
    doc["modules"] = {"m": {}}
    doc["issues"] = [1, 2]
    assert pm.summarize_memory(doc).startswith("1 files")

    hint = pm.format_aspects_hint(
        {"aspects": {"morrigan": {"notes": ["prefers pytest"]}}},
        "morrigan",
    )
    assert "pytest" in hint


def test_plan_schema_next_ready_depends():
    from services.plan_schema import Plan, PlanStep

    a = PlanStep(title="a", description="", status="pending", id="s1")
    b = PlanStep(title="b", description="", status="pending", id="s2", depends_on=["s1"])
    p = Plan(goal="g", steps=[a, b])
    assert p.next_ready_step() and p.next_ready_step().id == "s1"
    a.status = "done"
    assert p.next_ready_step() and p.next_ready_step().id == "s2"
