"""Default browser security headers are present on responses (defense-in-depth)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def test_security_headers_present_on_health():
    r = _client().get("/health")
    h = r.headers
    assert "content-security-policy" in {k.lower() for k in h}
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("Referrer-Policy") == "no-referrer"
    assert "microphone=(self)" in (h.get("Permissions-Policy") or "")


def test_csp_blocks_framing_and_objects():
    csp = _client().get("/health").headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    # Inline scripts allowed (static UI ships them), external scripts are not.
    assert "script-src 'self' 'unsafe-inline'" in csp
