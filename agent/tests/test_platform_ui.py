"""Tests for platform UI API endpoints and chat repair verification."""


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
    """Verify chat/Enter/Send repair markers are present in served UI."""
    from fastapi.testclient import TestClient

    from main import app
    client = TestClient(app)
    r = client.get("/ui")
    assert r.status_code == 200, "GET /ui must return 200"
    html = r.text

    # Must serve full UI from file (not minimal fallback) for repair to apply
    assert 'id="msg-input"' in html, "UI must contain #msg-input"
    assert 'id="send-btn"' in html, "UI must contain #send-btn"

    # Single entry point: triggerSend (bootstrap); Enter and Send use it
    assert "triggerSend" in html, "single send entry point triggerSend must be present"
    assert "window.triggerSend" in html, "triggerSend exposed on window"
    assert 'id="send-btn"' in html and "triggerSend" in html, "Send button uses triggerSend (inline or ref)"

    # Early Enter listener (document keydown, capture)
    assert "document.addEventListener('keydown'" in html or 'document.addEventListener("keydown"' in html, "early keydown listener"
    assert "activeElement" in html and "msg-input" in html, "Enter checks activeElement and msg-input"

    # try/finally so bindChatInputNow always runs
    assert "} finally {" in html, "script must use finally block"
    assert "bindChatInputNow" in html, "bindChatInputNow must be present"
    assert "getElementById('msg-input')" in html or 'getElementById("msg-input")' in html, "bindChatInputNow looks up msg-input"
    assert "getElementById('send-btn')" in html or 'getElementById("send-btn")' in html, "bindChatInputNow looks up send-btn"

    # Cache-Control so browser does not use stale UI
    assert "no-store" in r.headers.get("cache-control", "").lower(), "Cache-Control: no-store for /ui"


def test_ui_chat_repair_in_file():
    """Verify chat repair markers exist in the UI file on disk (no server)."""
    from pathlib import Path

    ui_file = Path(__file__).resolve().parent.parent / "ui" / "index.html"
    assert ui_file.is_file(), f"UI file missing: {ui_file}"
    html = ui_file.read_text(encoding="utf-8")

    assert 'id="msg-input"' in html
    assert 'id="send-btn"' in html
    assert "} finally {" in html
    assert "bindChatInputNow" in html
    assert "window.triggerSend" in html
    assert "triggerSend" in html
    assert "window._mentionActive" in html
    assert "document.addEventListener('keydown'" in html or 'document.addEventListener("keydown"' in html
