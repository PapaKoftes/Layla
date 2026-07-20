"""
§16 Remote: auth middleware and endpoint allowlist.
Run from agent/: pytest tests/test_remote.py -v
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))



def test_remote_disabled_no_auth_required(monkeypatch):
    """When remote_enabled is False, requests succeed without Authorization."""
    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"remote_enabled": False})
    client = TestClient(main.app)
    r = client.get("/health")
    assert r.status_code in (200, 503)


def test_remote_localhost_bypasses_auth(monkeypatch):
    """Localhost bypasses auth only when the operator opts out of always-require
    (REQ-11: remote_enabled now implies require-auth-always unless explicitly
    disabled via remote_require_auth_always=False)."""
    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_require_auth_always": False,  # REQ-11: explicit loopback exemption
        "remote_api_key": "secret",
        "allow_legacy_remote_api_key": True,
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.get("/health")
    assert r.status_code in (200, 503)


def test_remote_non_localhost_requires_key(monkeypatch):
    """When remote_enabled True and request is non-localhost, missing Authorization header -> 401."""
    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "secret123",
        "allow_legacy_remote_api_key": True,
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.get("/health", headers={})
    assert r.status_code == 401
    data = r.json()
    assert data.get("error") == "unauthorized"


def test_remote_non_localhost_wrong_key_401(monkeypatch):
    """When remote_enabled True and non-localhost, wrong Bearer token -> 401."""
    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "secret123",
        "allow_legacy_remote_api_key": True,
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.get("/health", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert r.json().get("error") == "unauthorized"


def test_remote_non_localhost_correct_key_allowed(monkeypatch):
    """When remote_enabled True, non-localhost, correct key, allowed path -> request passes."""
    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "secret123",
        "allow_legacy_remote_api_key": True,
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.get("/health", headers={"Authorization": "Bearer secret123"})
    assert r.status_code in (200, 503)


def test_remote_mode_observe_blocks_agent(monkeypatch):
    """remote_mode observe: /health allowed, /agent forbidden for remote request."""
    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "k",
        "allow_legacy_remote_api_key": True,
        "remote_allow_endpoints": [],
        "remote_mode": "observe",
    })
    client = TestClient(main.app)
    r = client.post("/agent", json={"message": "hi", "allow_write": False, "allow_run": False}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 403
    assert r.json().get("error") == "forbidden"


def test_remote_mode_interactive_allows_agent(monkeypatch):
    """remote_mode interactive: /agent is allowed (with correct key)."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    monkeypatch.setattr(main, "_is_localhost", lambda host: False)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "remote_enabled": True,
        "remote_api_key": "k",
        "allow_legacy_remote_api_key": True,
        "remote_allow_endpoints": [],
        "remote_mode": "interactive",
    })
    mock_result = {"status": "finished", "steps": [{"result": "ok"}], "aspect": "morrigan", "aspect_name": "Morrigan", "refused": False, "refusal_reason": "", "ux_states": [], "memory_influenced": []}
    with patch("agent_loop.autonomous_run", side_effect=lambda *_a, **_k: mock_result), \
         patch("routers.agent._model_ready_message", return_value=None):
        client = TestClient(main.app)
        r = client.post("/agent", json={"message": "hi", "allow_write": False, "allow_run": False}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200


class TestEnablingRemoteIsNotAOneWayDoor:
    """The endpoint allowlist restricts REMOTE callers, not the operator at the keyboard.

    require_auth_always is auto-on whenever remote_enabled, which skipped the direct-loopback
    exemption and dropped the LOCAL operator through to the allowlist built for internet
    clients. Following the product's own remedy — rotate a tunnel token, then enable remote —
    produced: GET /ui/ with a valid Bearer -> 403, POST /settings with a valid Bearer -> 403.
    The operator could not load the app and could not turn the flag back off; recovery meant
    hand-editing runtime_config.json. Only /health still answered.

    The middleware was conflating two questions: "must this caller present a token?" (yes,
    even on loopback, once require_auth_always is on — that is the deliberate hardening
    against a header-stripping forwarder such as `ssh -R`/socat arriving on 127.0.0.1) and
    "is this caller remote, and therefore restricted to the allowlist?" — which a DIRECT
    loopback connection answers no to.

    All three assertions below must hold together. Dropping the token requirement, or
    exempting a tunnelled caller, would each "fix" the lockout by opening a hole.

    remote_mode is `observe` deliberately: /settings is genuinely allowlisted under
    `interactive` (47 paths), so the allowlist only bites in observe (3 paths) and a test
    written against interactive would pass without proving anything.
    """

    TOKEN = "operator-test-token"

    def _cfg(self):
        import hashlib

        return {
            "remote_enabled": True,
            "tunnel_token_hash": hashlib.sha256(self.TOKEN.encode()).hexdigest(),
            "remote_mode": "observe",
            "remote_allow_endpoints": [],
        }

    def _client(self, monkeypatch):
        from fastapi.testclient import TestClient

        import main
        import runtime_safety

        cfg = self._cfg()
        monkeypatch.setattr(runtime_safety, "load_config", lambda: dict(cfg))
        return TestClient(main.app)

    def test_the_local_operator_keeps_their_machine(self, monkeypatch):
        """THE LOCKOUT. Direct loopback + a valid token must reach a non-allowlisted path."""
        client = self._client(monkeypatch)
        r = client.get("/settings", headers={"Authorization": "Bearer " + self.TOKEN})
        assert r.status_code == 200, (
            "the operator authenticated from the machine itself and still got %s — enabling "
            "remote access has locked them out of their own UI" % r.status_code
        )

    def test_a_tunnelled_caller_is_still_restricted(self, monkeypatch):
        """THE SECURITY HALF. A forwarded request is remote however loopback-shaped it looks."""
        client = self._client(monkeypatch)
        r = client.get(
            "/settings",
            headers={"Authorization": "Bearer " + self.TOKEN, "X-Forwarded-For": "203.0.113.9"},
        )
        assert r.status_code == 403, (
            "a tunnelled caller reached a non-allowlisted endpoint (%s) — the allowlist is "
            "the surface limit for remote access and must still apply" % r.status_code
        )

    def test_a_token_is_still_required_on_loopback(self, monkeypatch):
        """The `ssh -R`/socat hardening: require_auth_always still means what it says."""
        client = self._client(monkeypatch)
        r = client.get("/settings")
        assert r.status_code in (401, 403), (
            "loopback skipped authentication while require_auth_always was on (%s) — a "
            "header-stripping forwarder would walk straight in" % r.status_code
        )
