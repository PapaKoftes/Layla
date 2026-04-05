"""Cooperative background task cancel: POST /agent/tasks/{id}/cancel + DELETE alias."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def test_post_cancel_sets_cooperative_abort(monkeypatch, client):
    import routers.agent as ra

    def slow_autonomous_run(*_a, client_abort_event=None, **_k):
        for _ in range(200):
            if client_abort_event is not None and client_abort_event.is_set():
                return {
                    "status": "client_abort",
                    "response": "stopped",
                    "steps": [],
                    "aspect": "morrigan",
                    "aspect_name": "Morrigan",
                    "ux_states": [],
                    "memory_influenced": [],
                }
            time.sleep(0.02)
        return {
            "status": "finished",
            "response": "done",
            "steps": [],
            "aspect": "morrigan",
            "aspect_name": "Morrigan",
            "ux_states": [],
            "memory_influenced": [],
        }

    monkeypatch.setattr(ra, "autonomous_run", slow_autonomous_run)
    r = client.post("/agents/spawn", json={"message": "long task"})
    assert r.status_code == 200
    tid = r.json().get("task_id")
    assert tid
    c1 = client.post(f"/agent/tasks/{tid}/cancel")
    assert c1.status_code == 200
    assert c1.json().get("status") == "cancelled"
    for _ in range(80):
        g = client.get(f"/agent/tasks/{tid}")
        assert g.status_code == 200
        st = (g.json().get("task") or {}).get("status")
        if st == "cancelled":
            break
        time.sleep(0.05)
    else:
        pytest.fail("task did not reach cancelled status")
    g2 = client.get(f"/agent/tasks/{tid}")
    task = g2.json().get("task") or {}
    assert "cancel_event" not in task


def test_delete_cancel_idempotent(monkeypatch, client):
    import routers.agent as ra

    done = threading.Event()

    def fast_run(*_a, **_k):
        done.set()
        return {
            "status": "finished",
            "response": "ok",
            "steps": [],
            "aspect": "morrigan",
            "aspect_name": "Morrigan",
            "ux_states": [],
            "memory_influenced": [],
        }

    monkeypatch.setattr(ra, "autonomous_run", fast_run)
    r = client.post("/agents/spawn", json={"message": "quick"})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    assert done.wait(timeout=25)
    time.sleep(0.05)
    d1 = client.delete(f"/agent/tasks/{tid}")
    assert d1.status_code == 200
    body = d1.json()
    assert body.get("idempotent") is True
