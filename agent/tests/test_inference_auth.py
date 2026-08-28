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


def test_same_origin_and_plaintext_helpers():
    from services.llm.inference_router import _same_origin, _is_plaintext_nonlocal
    assert _same_origin("https://api.x.co/v1", "https://api.x.co/other")
    assert not _same_origin("https://api.x.co", "https://evil.y.co")
    assert not _same_origin("https://api.x.co", "http://api.x.co")   # scheme differs
    assert _is_plaintext_nonlocal("http://1.2.3.4:8000")
    assert not _is_plaintext_nonlocal("http://127.0.0.1:8000")       # loopback is fine
    assert not _is_plaintext_nonlocal("https://api.x.co")            # https is fine


def test_bearer_token_not_leaked_to_crossorigin_fallback(monkeypatch):
    """The Bearer token must go ONLY to the primary origin, never to a cross-host failover URL."""
    import urllib.request
    import urllib.error
    import threading
    from services.llm import inference_router as ir

    monkeypatch.setattr("services.safety.secret_store.get_secret", lambda name, default=None: default, raising=False)
    seen = []

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(req, timeout=0):
        seen.append((req.full_url, dict(req.headers)))
        if "primary" in req.full_url:                    # force failover off the primary
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    cfg = {
        "llama_server_url": "https://primary.test",
        "inference_fallback_urls": ["https://fallback.test"],
        "inference_api_key": "sk-secret-xyz",
    }
    ir.run_completion_openai_compatible(cfg, "hi", 16, 0.7, 0.9, 1.0, 40, [], False, 5, threading.Lock())
    hdrs = {url: h for url, h in seen}
    primary = next(u for u in hdrs if "primary" in u)
    fallback = next(u for u in hdrs if "fallback" in u)
    # header keys are case-insensitive via urllib; normalize
    assert any(k.lower() == "authorization" for k in hdrs[primary]), "primary must carry the Bearer token"
    assert not any(k.lower() == "authorization" for k in hdrs[fallback]), "fallback must NOT receive the token"
