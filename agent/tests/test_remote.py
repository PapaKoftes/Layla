"""
§16 Remote: auth middleware and endpoint allowlist.
Run from agent/: pytest tests/test_remote.py -v
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import pytest


def test_remote_disabled_no_auth_required(monkeypatch):
    """When remote_enabled is False, requests succeed without Authorization."""
    import runtime_safety
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"remote_enabled": False})
    client = TestClient(main.app)
    r = client.get("/health")
    assert r.status_code in (200, 503)


def test_remote_localhost_bypasses_auth(monkeypatch):
    """When remote_enabled True, localhost requests are not required to send API key."""
    import runtime_safety
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "secret",
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.get("/health")
    assert r.status_code in (200, 503)


def test_remote_non_localhost_requires_key(monkeypatch):
    """When remote_enabled True and request is non-localhost, missing Authorization header -> 401."""
    import runtime_safety
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "secret123",
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.get("/health", headers={})
    assert r.status_code == 401
    data = r.json()
    assert data.get("error") == "unauthorized"


def test_remote_non_localhost_wrong_key_401(monkeypatch):
    """When remote_enabled True and non-localhost, wrong Bearer token -> 401."""
    import runtime_safety
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "secret123",
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.get("/health", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert r.json().get("error") == "unauthorized"


def test_remote_non_localhost_correct_key_allowed(monkeypatch):
    """When remote_enabled True, non-localhost, correct key, allowed path -> request passes."""
    import runtime_safety
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "secret123",
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.get("/health", headers={"Authorization": "Bearer secret123"})
    assert r.status_code in (200, 503)


def test_remote_mode_observe_blocks_agent(monkeypatch):
    """remote_mode observe: /health allowed, /agent forbidden for remote request."""
    import runtime_safety
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "k",
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.post("/agent", json={"message": "hi", "allow_write": False, "allow_run": False}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 403
    assert r.json().get("error") == "forbidden"


def test_remote_mode_interactive_allows_agent(monkeypatch):
    """remote_mode interactive: /agent is allowed (with correct key)."""
    import runtime_safety
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    import main
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "k",
        "remote_allow_endpoints": [],
        "remote_mode": "interactive",
    })
    mock_result = {"status": "finished", "steps": [{"result": "ok"}], "aspect": "morrigan", "aspect_name": "Morrigan", "refused": False, "refusal_reason": "", "ux_states": [], "memory_influenced": []}
    with patch("routers.agent.autonomous_run", return_value=mock_result):
        client = TestClient(main.app)
        r = client.post("/agent", json={"message": "hi", "allow_write": False, "allow_run": False}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200