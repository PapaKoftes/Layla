"""Wave-1 security hardening ratchets — lock in the fail-closed / least-privilege fixes so a
future edit that reintroduces the fail-open or the raw-goal exec fails CI loudly."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_run_python_prefers_validated_code_arg():
    from services.tools.tool_dispatch import _run_python_code
    # validated structured arg wins over the whole goal string
    assert _run_python_code({"args": {"code": "print(1)"}}, "the entire goal string") == "print(1)"
    # fall back to goal only when there is no usable code arg
    assert _run_python_code({"args": {}}, "fallback goal") == "fallback goal"
    assert _run_python_code({}, "fallback goal") == "fallback goal"
    assert _run_python_code({"args": {"code": "   "}}, "fallback goal") == "fallback goal"


def test_pip_install_confines_empty_cwd(monkeypatch):
    from layla.tools.impl import system as sysmod
    monkeypatch.setattr(sysmod, "inside_sandbox", lambda p: False)
    # cwd="" used to skip the sandbox check entirely; it must now still be confined.
    r = sysmod.pip_install("requests", cwd="")
    assert r["ok"] is False and "sandbox" in r["error"]


@pytest.mark.endpoint
def test_agent_input_guard_fails_closed(monkeypatch):
    """If the input content-guard raises, /agent must DECLINE (fail closed), not proceed to
    generation. Previously the exception was swallowed and the prompt passed through."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import agent as ag

    def _boom(*a, **k):
        raise RuntimeError("guard exploded")

    monkeypatch.setattr("services.safety.content_guard.check_input", _boom)
    monkeypatch.setattr("services.safety.auth.is_direct_local", lambda h, host: True)
    monkeypatch.setattr(ag, "get_touch_activity", lambda: (lambda: None), raising=False)
    monkeypatch.setattr(ag, "get_append_history", lambda: (lambda *a, **k: None), raising=False)
    monkeypatch.setattr(ag, "get_conv_history", lambda cid: [], raising=False)

    app = FastAPI(); app.include_router(ag.router)
    tc = TestClient(app, raise_server_exceptions=False)
    r = tc.post("/agent", json={"message": "explain how python decorators work in detail", "stream": False})
    body = r.json()
    assert body.get("refused") is True
    assert body.get("refusal_reason") == "content_policy"
