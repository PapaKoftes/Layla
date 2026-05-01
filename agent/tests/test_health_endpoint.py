import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.endpoint

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from main import app  # noqa: E402


def test_health_fast_shape():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code in (200, 503)
    payload = r.json()
    assert "status" in payload
    assert "db_ok" in payload
    assert "uptime_seconds" in payload
    assert "knowledge_index_ready" in payload
    assert "knowledge_index_status" in payload
    assert payload["knowledge_index_ready"] is None or isinstance(payload["knowledge_index_ready"], bool)
    assert payload["knowledge_index_status"] is None or isinstance(payload["knowledge_index_status"], str)
    assert "effective_limits" in payload
    el = payload["effective_limits"]
    assert isinstance(el, dict)
    assert "max_tool_calls" in el
    assert "max_runtime_seconds" in el
    assert "response_cache_stats" in payload
    rs = payload["response_cache_stats"]
    assert isinstance(rs, dict)
    assert "hits" in rs and "misses" in rs
    assert "active_model" in payload
    assert isinstance(payload.get("active_model"), str)
    assert "effective_config" in payload
    ec = payload["effective_config"]
    assert isinstance(ec, dict)
    assert "effective_caps" in ec
    assert "features_enabled" in payload
    fe = payload["features_enabled"]
    assert isinstance(fe, dict)
    assert "chroma" in fe and isinstance(fe["chroma"], bool)
    assert "dependencies" in payload
    dep = payload["dependencies"]
    assert isinstance(dep, dict)
    for key in ("llama_cpp", "chroma", "voice_stt", "voice_tts", "tree_sitter"):
        assert key in dep
        assert dep[key] in ("ok", "missing", "error", "none", "unknown")


def test_health_deep_param():
    client = TestClient(app)
    r = client.get("/health?deep=true")
    assert r.status_code in (200, 503)
    payload = r.json()
    assert "chroma_ok" in payload


def test_health_deps_route():
    client = TestClient(app)
    r = client.get("/health/deps")
    assert r.status_code == 200
    data = r.json()
    assert "dependencies" in data
    dep = data["dependencies"]
    assert isinstance(dep, dict)
    assert "llama_cpp" in dep


def test_setup_download_rejects_invalid_filename():
    """Filename must not contain NUL or control chars (path / trust boundary)."""
    client = TestClient(app)
    r = client.get(
        "/setup/download",
        params={"url": "https://example.com/files/x.gguf", "filename": "bad\x00x.gguf"},
    )
    assert r.status_code == 200
    assert "Invalid filename" in r.text or '"error"' in r.text
