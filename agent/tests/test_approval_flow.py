"""
Approval flow: pending, approve (no bypass). Research pipeline helpers.
Run from agent/: pytest tests/test_approval_flow.py -v
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import pytest


def test_pending_returns_200_and_list():
    """GET /pending returns 200 and { pending: list }."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/pending")
    assert r.status_code == 200
    data = r.json()
    assert "pending" in data
    assert isinstance(data["pending"], list)


def test_approve_rejects_no_id():
    """POST /approve without id returns error."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.post("/approve", json={})
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is False
    assert "error" in data or "No id" in str(data).lower()


def test_approve_not_found():
    """POST /approve with nonexistent id returns not found."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.post("/approve", json={"id": "nonexistent-uuid-12345"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is False
    assert "not found" in str(data.get("error", "")).lower() or "not found" in str(data).lower()


def test_research_stages_load_mission_state():
    """Research pipeline: load_mission_state returns dict with stage, progress, completed."""
    from research_stages import load_mission_state
    state = load_mission_state()
    assert isinstance(state, dict)
    assert "stage" in state
    assert "progress" in state
    assert "completed" in state


def test_research_stages_is_useful_output():
    """Research pipeline: is_useful_output gates on actionable signals."""
    from research_stages import is_useful_output
    assert is_useful_output("") is False
    assert is_useful_output("   \n  ") is False
    assert is_useful_output("We should refactor this.") is True
    assert is_useful_output("Recommend using asyncio.") is True
    assert is_useful_output("Hello world.") is False