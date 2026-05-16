"""
End-to-end test: POST /agent returns 200 and expected shape when autonomous_run is mocked.
Run from agent/: pytest tests/test_e2e_agent.py -v
"""
import sys

import pytest

pytestmark = pytest.mark.endpoint
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))



def test_agent_endpoint_returns_200_with_mock_run():
    """POST /agent with a simple goal; mock autonomous_run to avoid loading LLM."""
    from fastapi.testclient import TestClient

    from main import app

    mock_result = {
        "status": "finished",
        "steps": [{"result": "Mocked reply for e2e test."}],
        "aspect": "morrigan",
        "aspect_name": "Morrigan",
        "refused": False,
        "refusal_reason": "",
        "ux_states": [],
        "memory_influenced": [],
    }

    def _mock_run(*_a, **_k):
        return mock_result

    with patch("agent_loop.autonomous_run", side_effect=_mock_run), \
         patch("routers.agent._model_ready_message", return_value=None):
        client = TestClient(app)
        r = client.post(
            "/agent",
            json={"message": "Say hello in one word.", "allow_write": False, "allow_run": False},
        )
    assert r.status_code == 200
    data = r.json()
    assert "response" in data
    assert data.get("response") == "Mocked reply for e2e test."
    assert data.get("aspect_name") == "Morrigan"
    assert "state" in data
    assert "cited_sources" in data
    assert isinstance(data["cited_sources"], list)
