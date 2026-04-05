"""Tests for platform UI API endpoints and chat repair verification."""

from __future__ import annotations

from pathlib import Path

AGENT_UI = Path(__file__).resolve().parent.parent / "ui"


def _aggregate_ui_chat_contract_text() -> str:
    """Shell HTML plus all UI JS under agent/ui/js (bootstrap + app live here after extraction)."""
    parts: list[str] = []
    index = AGENT_UI / "index.html"
    if index.is_file():
        parts.append(index.read_text(encoding="utf-8"))
    js_dir = AGENT_UI / "js"
    if js_dir.is_dir():
        for p in sorted(js_dir.glob("*.js")):
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_platform_models():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.get("/platform/models")
    assert r.status_code == 200
    d = r.json()
    assert "models" in d
    assert "active" in d
    assert "catalog" in d
    assert "benchmarks" in d
    assert isinstance(d["models"], list)


def test_platform_plugins():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.get("/platform/plugins")
    assert r.status_code == 200
    d = r.json()
    assert "skills_added" in d
    assert "tools_added" in d
    assert "capabilities_added" in d
    assert "skills" in d


def test_platform_knowledge():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.get("/platform/knowledge")
    assert r.status_code == 200
    d = r.json()
    assert "summaries" in d
    assert "learnings" in d
    assert "graph_nodes" in d
    assert "timeline" in d
    assert "user_identity" in d


def test_platform_projects():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.get("/platform/projects")
    assert r.status_code == 200
    d = r.json()
    assert "project_name" in d
    assert "goals" in d
    assert "progress" in d
    assert "blockers" in d
    assert "last_discussed" in d


def test_ui_loads():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.get("/ui")
    assert r.status_code == 200
    assert "LAYLA" in r.text or "layla" in r.text.lower()
    assert "panel-health" in r.text or "platform-health" in r.text


def test_ui_chat_repair_verification():
    """GET /ui must expose chat shell; wiring verified via aggregated static UI sources."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.get("/ui")
    assert r.status_code == 200, "GET /ui must return 200"
    html = r.text

    assert 'id="msg-input"' in html, "UI must contain #msg-input"
    assert 'id="send-btn"' in html, "UI must contain #send-btn"
    assert "no-store" in r.headers.get("cache-control", "").lower(), "Cache-Control: no-store for /ui"

    contract = _aggregate_ui_chat_contract_text()
    assert "triggerSend" in contract, "triggerSend must be present in UI sources"
    assert "window.triggerSend" in contract, "triggerSend exposed on window"
    assert "document.addEventListener('keydown'" in contract or 'document.addEventListener("keydown"' in contract, (
        "keydown listener"
    )
    assert "activeElement" in contract and "msg-input" in contract, "Enter checks activeElement and msg-input"
    assert "} finally {" in contract, "script must use finally block for bindChatInputNow"
    assert "bindChatInputNow" in contract, "bindChatInputNow must be present"
    assert "getElementById('msg-input')" in contract or 'getElementById("msg-input")' in contract, "msg-input lookup"
    assert "getElementById('send-btn')" in contract or 'getElementById("send-btn")' in contract, "send-btn lookup"
    assert "window._mentionActive" in contract, "mention overlay flag"


def test_ui_chat_repair_in_file():
    """On-disk UI sources must still contain chat repair markers."""
    contract = _aggregate_ui_chat_contract_text()
    assert 'id="msg-input"' in contract
    assert 'id="send-btn"' in contract
    assert "} finally {" in contract
    assert "bindChatInputNow" in contract
    assert "window.triggerSend" in contract
    assert "triggerSend" in contract
    assert "window._mentionActive" in contract
    assert "document.addEventListener('keydown'" in contract or 'document.addEventListener("keydown"' in contract


def test_layla_ui_static_assets_served():
    """CSS and JS extracted under agent/ui must be reachable via /layla-ui."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.get("/layla-ui/css/layla.css")
    assert r.status_code == 200, "layla.css must be served"
    assert len(r.text) > 100
    r2 = client.get("/layla-ui/js/layla-app.js")
    assert r2.status_code == 200, "layla-app.js must be served"
    assert len(r2.text) > 100
