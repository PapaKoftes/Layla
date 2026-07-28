"""DNS-rebinding defense — the tool-executing agent API must reject unknown Host headers even in
the DEFAULT local-only mode (remote_enabled=False). Without it, a malicious web page that resolves
its own hostname to 127.0.0.1 could drive the local API through the victim's browser.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_unknown_host_header_is_rejected_in_local_mode():
    import main
    c = TestClient(main.app)

    # Known-local hosts are served (TestClient defaults to Host: testserver).
    assert c.get("/health").status_code == 200
    assert c.get("/health", headers={"host": "127.0.0.1:8016"}).status_code == 200
    assert c.get("/health", headers={"host": "localhost"}).status_code == 200

    # A rebound attacker host is refused, not served.
    r = c.get("/health", headers={"host": "evil.attacker.example"})
    assert r.status_code == 400 and r.json().get("error") == "host_not_allowed"
    assert c.get("/health", headers={"host": "10.0.0.5:8016"}).status_code == 400
