import sys
from pathlib import Path

from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from main import app  # noqa: E402


def test_mission_create_missing_goal():
    client = TestClient(app)
    r = client.post("/mission", json={})
    assert r.status_code == 400
    assert "goal required" in r.json().get("error", "").lower()


def test_mission_create_body_fields_propagate(monkeypatch):
    captured: dict = {}

    def _fake_create_mission(goal, workspace_root="", allow_write=False, allow_run=False, cfg=None):
        captured["goal"] = goal
        captured["workspace_root"] = workspace_root
        captured["allow_write"] = allow_write
        captured["allow_run"] = allow_run
        return {"id": "m-1", "goal": goal, "plan": [{"task": "x"}], "status": "pending"}

    def _fake_run_mission(_mission_id):
        return True

    import services.mission_manager as mm

    monkeypatch.setattr(mm, "create_mission", _fake_create_mission)
    monkeypatch.setattr(mm, "run_mission", _fake_run_mission)

    client = TestClient(app)
    payload = {
        "goal": "ship fix",
        "workspace_root": "C:/tmp/work",
        "allow_write": True,
        "allow_run": True,
    }
    r = client.post("/mission", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert captured["goal"] == payload["goal"]
    assert captured["workspace_root"] == payload["workspace_root"]
    assert captured["allow_write"] is True
    assert captured["allow_run"] is True


def test_mission_get_not_found():
    client = TestClient(app)
    r = client.get("/mission/fake-id")
    assert r.status_code == 404
    assert "not found" in r.json().get("error", "").lower()
