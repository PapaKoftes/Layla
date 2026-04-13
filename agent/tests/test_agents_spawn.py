"""POST /agents/spawn — same task store as /agent/background."""
import sys
import threading
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


@pytest.fixture(autouse=True)
def _clear_background_tasks_between_spawn_tests():
    """Daemon threads from /agents/spawn can finish after a test ends; drain store for isolation."""
    from services import agent_task_runner as atr

    with atr._TASKS_LOCK:
        atr._TASKS.clear()
    yield
    with atr._TASKS_LOCK:
        atr._TASKS.clear()


def test_agents_spawn_requires_message(client):
    r = client.post("/agents/spawn", json={})
    assert r.status_code == 400
    body = r.json()
    assert body.get("ok") is False


def test_agents_spawn_rejects_empty_message(client):
    r = client.post("/agents/spawn", json={"message": ""})
    assert r.status_code == 400
    assert r.json().get("ok") is False


def test_agents_spawn_returns_task_and_poll_path(client):
    r = client.post("/agents/spawn", json={"message": "say hi in one word"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    tid = body.get("task_id")
    assert tid and body.get("agent_id") == tid
    assert body.get("kind") == "tiny_agent"
    assert body.get("poll_path") == f"/agent/tasks/{tid}"
    g = client.get(f"/agent/tasks/{tid}")
    assert g.status_code == 200
    task = g.json().get("task") or {}
    assert task.get("task_id") == tid
    assert task.get("kind") == "tiny_agent"


def test_agents_spawn_task_ids_are_unique(client):
    r1 = client.post("/agents/spawn", json={"message": "hello one"})
    r2 = client.post("/agents/spawn", json={"message": "hello two"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json().get("task_id") != r2.json().get("task_id")


def test_agents_spawn_defaults_allow_write_allow_run_false(monkeypatch, client):
    import agent_loop

    done = threading.Event()
    captured: dict = {}
    marker = "ping-allow-flags-unit-test"

    def fake_autonomous_run(goal, context="", workspace_root="", allow_write=False, allow_run=False, **kwargs):
        if goal == marker:
            captured["allow_write"] = allow_write
            captured["allow_run"] = allow_run
            done.set()
        return {
            "status": "finished",
            "response": "ok",
            "steps": [{"action": "reason", "result": "ok"}],
            "aspect": "morrigan",
            "aspect_name": "Morrigan",
            "ux_states": [],
            "memory_influenced": [],
        }

    monkeypatch.setattr(agent_loop, "autonomous_run", fake_autonomous_run)
    r = client.post("/agents/spawn", json={"message": marker})
    assert r.status_code == 200
    assert done.wait(timeout=20)
    assert captured.get("allow_write") is False
    assert captured.get("allow_run") is False


def test_spawn_response_includes_effective_flags_and_workspace(client):
    ws = "/custom/spawn-workspace-root"
    r = client.post(
        "/agents/spawn",
        json={
            "message": "ping",
            "allow_write": True,
            "allow_run": False,
            "workspace_root": ws,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("allow_write") is True
    assert body.get("allow_run") is False
    assert body.get("workspace_root") == ws
    assert body.get("isolation", {}).get("conversation_scoped_history") is True


def test_agents_spawn_passes_workspace_root_to_autonomous_run(monkeypatch, client):
    import agent_loop

    done = threading.Event()
    captured: dict = {}
    marker = "ping-ws-root-unit-test"

    def fake_autonomous_run(goal, workspace_root="", **kwargs):
        if goal == marker:
            captured["workspace_root"] = workspace_root
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

    monkeypatch.setattr(agent_loop, "autonomous_run", fake_autonomous_run)
    ws = "/tmp/spawn-ws-unit-test"
    r = client.post("/agents/spawn", json={"message": marker, "workspace_root": ws})
    assert r.status_code == 200
    assert done.wait(timeout=20)
    assert captured.get("workspace_root") == ws


def test_spawn_uses_fresh_history_for_new_conversation_id(monkeypatch, client):
    """Separate conversation_id ⇒ separate deque in shared_state (no cross-leak by default)."""
    import agent_loop
    from shared_state import append_conv_history, get_conv_history

    append_conv_history("parent-session-xyz", "user", "SECRET_PARENT_ONLY")

    done = threading.Event()
    captured: dict = {}
    marker = "ping-fresh-history-unit-test"

    def fake_autonomous_run(goal, conversation_history=None, conversation_id="", **kwargs):
        if goal != marker:
            return {
                "status": "finished",
                "response": "ok",
                "steps": [],
                "aspect": "morrigan",
                "aspect_name": "Morrigan",
                "ux_states": [],
                "memory_influenced": [],
            }
        captured["conversation_id"] = conversation_id
        captured["history_len"] = len(conversation_history or [])
        captured["has_secret"] = any(
            "SECRET_PARENT_ONLY" in str((t or {}).get("content", "")) for t in (conversation_history or [])
        )
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

    monkeypatch.setattr(agent_loop, "autonomous_run", fake_autonomous_run)
    r = client.post("/agents/spawn", json={"message": marker, "conversation_id": "child-worker-abc"})
    assert r.status_code == 200
    assert r.json().get("conversation_id") == "child-worker-abc"
    assert done.wait(timeout=20)
    assert captured.get("conversation_id") == "child-worker-abc"
    assert captured.get("has_secret") is False
    assert captured.get("history_len") == 0
    # Sanity: parent history still exists
    assert any("SECRET_PARENT_ONLY" in str(x.get("content", "")) for x in get_conv_history("parent-session-xyz"))


def test_agents_spawn_passes_explicit_conversation_id(monkeypatch, client):
    import agent_loop

    done = threading.Event()
    captured: dict = {}
    cid = "spawn-test-conversation-id"

    cid_marker = "ping-explicit-conv-id-unit-test"

    def fake_autonomous_run(goal, **kwargs):
        if goal == cid_marker:
            captured["conversation_id"] = kwargs.get("conversation_id")
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

    monkeypatch.setattr(agent_loop, "autonomous_run", fake_autonomous_run)
    r = client.post("/agents/spawn", json={"message": cid_marker, "conversation_id": cid})
    assert r.status_code == 200
    assert r.json().get("conversation_id") == cid
    assert done.wait(timeout=20)
    assert captured.get("conversation_id") == cid
