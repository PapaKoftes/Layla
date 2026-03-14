"""
Smoke test: verify all required modules for startup are present.
Catches ModuleNotFoundError before uvicorn runs (e.g. after fresh clone).
Run from agent/: pytest tests/test_startup_imports.py -v
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_main_app_loads():
    """main:app must load without ModuleNotFoundError (critical for Linux startup)."""
    from main import app
    assert app is not None


def test_agent_loop_imports():
    """agent_loop top-level imports must succeed."""
    from agent_loop import autonomous_run, _is_junk_reply
    assert callable(autonomous_run)
    assert callable(_is_junk_reply)


def test_context_manager_available():
    """context_manager is required by agent_loop at load time."""
    from services.context_manager import build_system_prompt, DEFAULT_BUDGETS
    assert callable(build_system_prompt)
    assert isinstance(DEFAULT_BUDGETS, dict)


def test_health_endpoint_responds():
    """FastAPI app serves /health."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
