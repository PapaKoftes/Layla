"""HTTP routes for /workspace/cognition* (repo cognition packs)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.memory import db as db_mod  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "_DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_MIGRATED", False)
    db_mod.migrate()
    return TestClient(app)


def test_workspace_cognition_list_ok(client):
    r = client.get("/workspace/cognition")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert "snapshots" in body


def test_workspace_cognition_sync_minimal(client, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "README.md").write_text("# P\n\nHello.", encoding="utf-8")
    r = client.post(
        "/workspace/cognition/sync",
        json={"workspace_roots": [str(root.resolve())], "index_semantic": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
