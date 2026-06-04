"""Tests for the remote trust boundary (services/auth.py).

Regression guard for the CRITICAL finding: a tunnel (cloudflared/ngrok) forwards
internet traffic to the app from 127.0.0.1, so a bare loopback check exempted
every remote request from auth. real_client_ip()/is_direct_local() must treat a
forwarded request as NON-local even when the socket address is loopback.
Pure stdlib — runs on 3.14.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.auth import is_direct_local, real_client_ip  # noqa: E402


class _Headers:
    """Case-insensitive header stub mimicking Starlette's headers.get()."""
    def __init__(self, d=None):
        self._d = {k.lower(): v for k, v in (d or {}).items()}
    def get(self, k):
        return self._d.get(str(k).lower())


# ---- validation: the trusted path still works ----
def test_direct_loopback_is_local():
    assert is_direct_local(_Headers({}), "127.0.0.1") is True
    assert is_direct_local(_Headers({}), "::1") is True
    assert is_direct_local(_Headers({}), "localhost") is True


# ---- failure mode the fix closes: tunnelled loopback is NOT local ----
def test_tunnelled_loopback_is_not_local():
    # cloudflared
    assert is_direct_local(_Headers({"Cf-Connecting-Ip": "203.0.113.9"}), "127.0.0.1") is False
    # ngrok / generic proxy
    assert is_direct_local(_Headers({"X-Forwarded-For": "203.0.113.9, 127.0.0.1"}), "127.0.0.1") is False
    assert is_direct_local(_Headers({"X-Real-Ip": "203.0.113.9"}), "127.0.0.1") is False
    assert is_direct_local(_Headers({"Forwarded": 'for=203.0.113.9;proto=https'}), "127.0.0.1") is False
    assert is_direct_local(_Headers({"True-Client-Ip": "203.0.113.9"}), "127.0.0.1") is False


# ---- real client IP is extracted for allowlist/rate-limit/audit ----
def test_real_client_ip_extraction():
    ip, via = real_client_ip(_Headers({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}), "127.0.0.1")
    assert ip == "203.0.113.9" and via is True
    ip2, via2 = real_client_ip(_Headers({"Forwarded": 'for="203.0.113.9:4711"'}), "127.0.0.1")
    assert ip2.startswith("203.0.113.9") and via2 is True
    ip3, via3 = real_client_ip(_Headers({}), "203.0.113.50")
    assert ip3 == "203.0.113.50" and via3 is False


# ---- a direct remote connection is also non-local ----
def test_direct_remote_is_not_local():
    assert is_direct_local(_Headers({}), "203.0.113.9") is False
    assert is_direct_local(_Headers({}), "10.0.0.5") is False


# ---- edge cases ----
def test_lan_attacker_cannot_spoof_forwarding_header():
    # When the request did NOT arrive on loopback, forwarding headers are
    # client-spoofable and must be IGNORED — use the real socket peer.
    ip, via = real_client_ip(_Headers({"X-Forwarded-For": "127.0.0.1"}), "10.0.0.7")
    assert ip == "10.0.0.7" and via is False
    assert is_direct_local(_Headers({"X-Forwarded-For": "127.0.0.1"}), "10.0.0.7") is False


def test_provider_header_preferred_over_xff():
    # Cf-Connecting-Ip (provider-set, not client-forgeable) wins over the
    # client-appendable X-Forwarded-For.
    ip, via = real_client_ip(_Headers({"X-Forwarded-For": "127.0.0.1", "Cf-Connecting-Ip": "203.0.113.9"}), "127.0.0.1")
    assert ip == "203.0.113.9" and via is True


def test_whitespace_forwarding_header_stays_direct():
    # A blank-but-present header must not flip a direct-local request to remote.
    assert is_direct_local(_Headers({"X-Forwarded-For": "   "}), "127.0.0.1") is True


def test_edge_cases():
    # no headers object at all
    assert real_client_ip(None, "127.0.0.1") == ("127.0.0.1", False)
    # empty forward header value is ignored (treated as direct)
    assert is_direct_local(_Headers({"X-Forwarded-For": ""}), "127.0.0.1") is True
    # missing socket host + no headers -> conservative local (dev)
    assert is_direct_local(_Headers({}), None) is True
    # IPv6-mapped loopback direct
    assert is_direct_local(_Headers({}), "::ffff:127.0.0.1") is True
