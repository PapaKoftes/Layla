"""B1 release-blocker: client-facing errors must NOT leak raw exception text / internal
paths, and must carry a correct status code (info-disclosure + API-correctness)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

# A distinctive marker that would only appear if the raw exception leaked to the client.
_SECRET = "SECRET_LEAK_/home/user/.ssh/id_rsa"


def test_v1_error_sanitized_and_500(monkeypatch):
    from routers import openai_compat as oc

    def _boom(goal=None, **kw):
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(oc, "autonomous_run", _boom, raising=False)
    monkeypatch.setattr(oc, "get_append_history", lambda: (lambda *a, **k: None), raising=False)
    monkeypatch.setattr(oc, "_quick_reply_for_trivial_turn", lambda g: "", raising=False)
    monkeypatch.setattr("services.safety.auth.is_direct_local", lambda h, host: True)
    app = FastAPI(); app.include_router(oc.router)
    tc = TestClient(app, raise_server_exceptions=False)
    r = tc.post("/v1/chat/completions", json={"model": "layla", "messages": [{"role": "user", "content": "hello there"}]})
    assert r.status_code == 500
    assert _SECRET not in r.text
    assert "Internal server error" in r.text


def test_agent_error_sanitized_and_500(monkeypatch):
    import main
    from routers import agent as ag

    def _boom(goal, **kw):
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(ag, "_dispatch_autonomous_run", _boom, raising=False)
    monkeypatch.setattr(ag, "_model_ready_message", lambda: None, raising=False)  # pretend model is loaded
    tc = TestClient(main.app, raise_server_exceptions=False)
    r = tc.post("/agent", json={"message": "hello", "stream": False})
    # Core B1 guarantee: never leak the raw exception, and don't return HTTP 200 on failure.
    assert r.status_code == 500
    assert _SECRET not in r.text


def test_global_exception_handler_sanitizes(monkeypatch):
    """Unhandled errors on any route go through the app-level handler → sanitized 500."""
    import main

    @main.app.get("/_boom_test_route")
    async def _boom_route():
        raise RuntimeError(_SECRET)

    tc = TestClient(main.app, raise_server_exceptions=False)
    r = tc.get("/_boom_test_route")
    assert r.status_code == 500
    assert _SECRET not in r.text
    assert "Internal server error" in r.text


def test_routers_never_return_raw_exception_text_in_500():
    # audit #13: cluster/memory/onboarding 500 handlers returned `detail=str(e)`, leaking absolute
    # Windows paths (C:\Users\<name>\...) — the OS username is PII — and internal file layout. They now
    # log server-side and return a generic detail. Guard against the exact regression re-appearing.
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    for rel in ("routers/cluster.py", "routers/memory.py", "routers/onboarding.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "status_code=500, detail=str(" not in src, f"{rel} leaks raw exception text in a 500"
