"""Audit C1: /v1 must strip allow_write/allow_run from a REMOTE caller (RCE guard).

The primitive is_direct_local() is tested elsewhere; this proves the wiring in
v1_chat_completions actually forces allow_run=allow_write=False for a non-local caller,
honours them for a loopback caller, and fails CLOSED if the trust check raises. A
regression here turns the chat endpoint into a remote RCE primitive.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import openai_compat as oc


@pytest.fixture
def client_capturing(monkeypatch):
    captured = {}

    def _fake_autonomous_run(goal=None, **kwargs):
        captured["allow_write"] = kwargs.get("allow_write")
        captured["allow_run"] = kwargs.get("allow_run")
        return {"response": "ok", "steps": [], "aspect": "morrigan"}

    # the handler calls autonomous_run (non-stream path) — capture what it's invoked with
    monkeypatch.setattr(oc, "autonomous_run", _fake_autonomous_run, raising=False)
    # avoid the trivial-turn shortcut so we reach the agent invocation
    monkeypatch.setattr(oc, "_quick_reply_for_trivial_turn", lambda g: "", raising=False)
    # shared_state isn't initialized in a bare TestClient app — stub the history sink
    monkeypatch.setattr(oc, "get_append_history", lambda: (lambda *a, **k: None), raising=False)

    app = FastAPI()
    app.include_router(oc.router)
    return TestClient(app), captured, monkeypatch


def _post(client, body):
    return client.post("/v1/chat/completions", json=body)


def test_remote_caller_cannot_self_grant(client_capturing):
    client, captured, mp = client_capturing
    mp.setattr("services.safety.auth.is_direct_local", lambda headers, host: False)
    r = _post(client, {"model": "layla", "allow_write": True, "allow_run": True,
                       "messages": [{"role": "user", "content": "do something"}]})
    assert r.status_code == 200
    # even though the body asked for write+run, a remote caller must get neither
    assert captured["allow_write"] is False
    assert captured["allow_run"] is False


def test_local_caller_keeps_grants(client_capturing):
    client, captured, mp = client_capturing
    mp.setattr("services.safety.auth.is_direct_local", lambda headers, host: True)
    _post(client, {"model": "layla", "allow_write": True, "allow_run": True,
                   "messages": [{"role": "user", "content": "do something"}]})
    assert captured["allow_write"] is True
    assert captured["allow_run"] is True


def test_trust_check_failure_fails_closed(client_capturing):
    client, captured, mp = client_capturing

    def _boom(headers, host):
        raise RuntimeError("trust check exploded")

    mp.setattr("services.safety.auth.is_direct_local", _boom)
    _post(client, {"model": "layla", "allow_write": True, "allow_run": True,
                   "messages": [{"role": "user", "content": "do something"}]})
    # an exception in the trust check must NOT leave the caller with grants
    assert captured["allow_write"] is False
    assert captured["allow_run"] is False
