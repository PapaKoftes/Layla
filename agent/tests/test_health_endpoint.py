import sys
from pathlib import Path

from fastapi.testclient import TestClient

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


def test_health_deep_param():
    client = TestClient(app)
    r = client.get("/health?deep=true")
    assert r.status_code in (200, 503)
    payload = r.json()
    assert "chroma_ok" in payload
