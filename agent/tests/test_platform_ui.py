"""Tests for platform UI API endpoints."""


def test_platform_models():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/platform/models")
    assert r.status_code == 200
    d = r.json()
    assert "models" in d
    assert "active" in d
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


def test_ui_loads():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/ui")
    assert r.status_code == 200
    assert "LAYLA" in r.text or "layla" in r.text.lower()
    assert "panel-health" in r.text or "platform-health" in r.text
