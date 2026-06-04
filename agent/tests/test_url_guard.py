"""Tests for the hardened SSRF guard (agent/services/url_guard.py).

Pure stdlib, no app import. resolve=False is used where we only want to test the
scheme/literal-IP logic without real DNS.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.url_guard import check_url, is_safe_url  # noqa: E402

BLOCKED = [
    "http://127.0.0.1/",
    "http://localhost/",          # resolves to loopback
    "http://10.0.0.5/admin",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",                  # IPv4-mapped IPv6
    "http://2130706433/",                          # decimal 127.0.0.1
    "http://0x7f.0.0.1/",                          # hex
    "http://0177.0.0.1/",                          # octal
    "http://0.0.0.0/",
    "file:///etc/passwd",
    "ftp://example.com/x",
    "gopher://127.0.0.1/",
    "http://user:pass@example.com/",               # credentials in url
    "not a url",
    "",
]

ALLOWED_LITERALS = [
    "http://8.8.8.8/",
    "https://1.1.1.1/",
    "http://93.184.216.34/",      # example.com's historical IP, public
]


def test_blocked_urls_are_unsafe():
    for u in BLOCKED:
        ok, reason = check_url(u, resolve=True)
        assert ok is False, f"expected BLOCKED but allowed: {u} ({reason})"


def test_public_ip_literals_allowed():
    for u in ALLOWED_LITERALS:
        assert is_safe_url(u, resolve=True) is True, f"expected allowed: {u}"


def test_scheme_enforced_without_resolution():
    assert is_safe_url("file:///etc/passwd", resolve=False) is False
    assert is_safe_url("ftp://host/x", resolve=False) is False
    assert is_safe_url("https://example.com/x", resolve=False) is True


def test_obfuscated_loopback_blocked_without_resolution():
    # decimal/hex/octal IPv4 are caught as literals, no DNS needed
    assert is_safe_url("http://2130706433/", resolve=False) is False
    assert is_safe_url("http://0x7f.0.0.1/", resolve=False) is False


def test_reason_is_descriptive():
    ok, reason = check_url("http://169.254.169.254/", resolve=True)
    assert not ok and "blocked" in reason.lower()
    ok2, reason2 = check_url("ftp://x/y")
    assert not ok2 and "scheme" in reason2.lower()
