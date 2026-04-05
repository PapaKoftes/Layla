"""Projects API smoke tests."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from main import app  # noqa: E402


def test_projects_list_ok():
    client = TestClient(app)
    r = client.get("/projects")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert "projects" in body
    assert isinstance(body["projects"], list)


def test_projects_create_get_patch_delete():
    client = TestClient(app)
    pid = str(uuid.uuid4())
    r = client.post(
        "/projects",
        json={
            "id": pid,
            "name": "pytest project",
            "workspace_root": str(Path.home()),
            "aspect_default": "morrigan",
            "skill_paths_json": "[]",
            "system_preamble": "Test preamble.",
        },
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True
    proj = r.json().get("project") or {}
    assert proj.get("id") == pid

    r2 = client.get(f"/projects/{pid}")
    assert r2.status_code == 200
    assert r2.json().get("ok") is True

    r3 = client.patch(f"/projects/{pid}", json={"name": "pytest project renamed"})
    assert r3.status_code == 200
    assert r3.json().get("ok") is True

    r4 = client.delete(f"/projects/{pid}")
    assert r4.status_code == 200
    assert r4.json().get("ok") is True

    r5 = client.get(f"/projects/{pid}")
    assert r5.status_code == 404
