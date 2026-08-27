"""Outbound Bearer auth for the OpenAI-compatible inference path.

Before: the openai_compatible backend sent no Authorization header, so it only worked against
unauthenticated local servers (vLLM) — it could NOT reach an authenticated cloud endpoint (OpenRouter /
OpenAI / together / a secured vLLM). `inference_api_key` now adds `Authorization: Bearer <key>` when set,
which is the foundation for using a frontier model while keeping local as the default.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_auth_headers_adds_bearer_when_key_set():
    from services.llm.inference_router import _auth_headers
    h = _auth_headers({"inference_api_key": "sk-test-123"})
    assert h["Authorization"] == "Bearer sk-test-123"
    assert h["Content-Type"] == "application/json"


def test_auth_headers_no_bearer_when_absent():
    from services.llm.inference_router import _auth_headers
    for cfg in ({}, {"inference_api_key": ""}, {"inference_api_key": "   "}):
        assert "Authorization" not in _auth_headers(cfg)


def test_inference_api_key_is_treated_as_secret():
    """Name contains 'api_key' -> the secret filter redacts it in GET /settings and it is keyring-routed."""
    from services.safety.secret_filter import is_secret_key
    assert is_secret_key("inference_api_key") is True
