"""Session export checkpoint JSON (operator backup)."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from main import app  # noqa: E402


def test_session_export_shape():
    client = TestClient(app)
    r = client.get("/session/export")
    assert r.status_code == 200
    data = r.json()
    assert "exported_at" in data
    assert "version" in data
    assert "pending_approvals" in data
    assert isinstance(data["pending_approvals"], list)
    assert "server_history_tail" in data
    assert isinstance(data["server_history_tail"], list)
    assert data.get("conversation_id") in (None, "")


def test_values_md_serves_when_present():
    client = TestClient(app)
    r = client.get("/values.md")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert "markdown" in (r.headers.get("content-type") or "").lower() or len(r.text) > 50
