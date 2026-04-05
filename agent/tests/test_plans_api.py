"""layla_plans API: create, list, patch, approve, execute (mocked agent)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture
def client(monkeypatch, tmp_path):
    import layla.memory.db as db_mod

    db_path = tmp_path / "tplans.db"
    monkeypatch.setattr(db_mod, "_DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_MIGRATED", False)
    db_mod.migrate()
    from main import app

    return TestClient(app)


def test_plans_create_list_get_patch_approve(client, monkeypatch):
    r = client.post(
        "/plans",
        json={
            "goal": "test goal",
            "context": "ctx",
            "workspace_root": str(Path.home()),
            "steps": [
                {"id": 1, "type": "analysis", "description": "Step one", "status": "pending"},
            ],
        },
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    pid = j.get("plan_id")
    assert pid

    r2 = client.get("/plans")
    assert r2.status_code == 200
    plans = r2.json().get("plans") or []
    assert any(p.get("id") == pid for p in plans)

    r3 = client.get(f"/plans/{pid}")
    assert r3.status_code == 200
    assert r3.json().get("plan", {}).get("status") == "draft"

    r4 = client.patch(
        f"/plans/{pid}",
        json={"goal": "updated goal"},
    )
    assert r4.status_code == 200
    j4 = r4.json()
    assert j4.get("plan", {}).get("goal") == "updated goal"
    assert "suggestions" not in j4

    r4b = client.patch(
        f"/plans/{pid}",
        json={
            "steps": [
                {"id": 1, "type": "edit", "description": "short", "status": "pending"},
            ],
        },
    )
    assert r4b.status_code == 200
    j4b = r4b.json()
    sug = j4b.get("suggestions") or []
    assert isinstance(sug, list) and len(sug) >= 1

    r5 = client.post(f"/plans/{pid}/approve")
    assert r5.status_code == 200
    assert r5.json().get("plan", {}).get("status") == "approved"


def test_plans_execute_calls_planner(monkeypatch, client):
    from services import planner as planner_mod

    called = []

    def fake_exec(plan, agent_run_fn, goal_prefix="", plan_depth=0, **kwargs):
        called.append((len(plan), kwargs.get("plan_approved"), kwargs.get("active_plan_id"), kwargs.get("step_governance")))
        return {"status": "plan_completed", "steps_done": [], "summary": "ok", "all_steps_ok": True}

    monkeypatch.setattr(planner_mod, "execute_plan", fake_exec)

    r = client.post(
        "/plans",
        json={
            "goal": "g",
            "steps": [{"id": 1, "type": "task", "description": "Do thing", "status": "pending"}],
        },
    )
    pid = r.json()["plan_id"]
    client.post(f"/plans/{pid}/approve")
    r2 = client.post(
        f"/plans/{pid}/execute",
        json={"allow_write": True, "allow_run": False},
    )
    assert r2.status_code == 200
    assert r2.json().get("ok") is True
    assert len(called) == 1
    assert called[0][0] == 1
    assert called[0][1] is True
    assert called[0][2] == pid
    assert called[0][3] is True


def test_plans_execute_rejects_unapproved(client):
    r = client.post("/plans", json={"goal": "x", "steps": [{"id": 1, "type": "t", "description": "d", "status": "pending"}]})
    pid = r.json()["plan_id"]
    r2 = client.post(f"/plans/{pid}/execute", json={})
    assert r2.status_code == 409


def test_plans_approve_rejects_empty_steps(client):
    r = client.post("/plans", json={"goal": "only goal", "steps": []})
    assert r.status_code == 200
    pid = r.json()["plan_id"]
    r2 = client.post(f"/plans/{pid}/approve")
    assert r2.status_code == 400
    assert r2.json().get("error") == "plan_validation_failed"
    assert "no_steps" in (r2.json().get("details") or [])


def test_plans_approve_rejects_edit_without_tools_when_required(client, monkeypatch):
    import services.plan_step_governance as psg

    monkeypatch.setattr(psg, "_plan_governance_require_nonempty_tools", lambda: True)
    r = client.post(
        "/plans",
        json={
            "goal": "g",
            "steps": [
                {"id": 1, "type": "edit", "description": "change implementation", "status": "pending", "tools": []},
            ],
        },
    )
    assert r.status_code == 200
    pid = r.json()["plan_id"]
    r2 = client.post(f"/plans/{pid}/approve")
    assert r2.status_code == 400
    assert r2.json().get("error") == "plan_validation_failed"
    assert any("missing_tools" in d for d in (r2.json().get("details") or []))
