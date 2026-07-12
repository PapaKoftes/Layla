"""Tests for the hardened SSRF guard (agent/services/url_guard.py).

Pure stdlib, no app import. resolve=False is used where we only want to test the
scheme/literal-IP logic without real DNS.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.safety.url_guard import check_url, is_safe_url  # noqa: E402

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


# ── safe_urlopen / safe_fetch_text: redirect-revalidating guarded fetch (audit round-1 SSRF cluster) ──

def test_safe_urlopen_blocks_internal_and_obfuscated():
    from services.safety.url_guard import safe_urlopen, SSRFBlocked
    import pytest
    for u in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:6379/",
              "http://[::1]/", "http://2130706433/", "http://192.168.0.1/"):
        with pytest.raises(SSRFBlocked):
            safe_urlopen(u, timeout=2)


def test_safe_urlopen_rejects_non_http_scheme():
    from services.safety.url_guard import safe_urlopen, SSRFBlocked
    import pytest
    with pytest.raises(SSRFBlocked):
        safe_urlopen("file:///etc/passwd", timeout=2)


def test_safe_fetch_text_returns_empty_on_block():
    # Drop-in for trafilatura.fetch_url in crawl/feed loops: blocked URL yields "" (skip), not a raise.
    from services.safety.url_guard import safe_fetch_text
    assert safe_fetch_text("http://169.254.169.254/", timeout=2) == ""
    assert safe_fetch_text("http://127.0.0.1:8000/admin", timeout=2) == ""


def test_safe_urlopen_blocks_ipv4_mapped_loopback():
    from services.safety.url_guard import safe_urlopen, SSRFBlocked
    import pytest
    with pytest.raises(SSRFBlocked):
        safe_urlopen("http://[::ffff:127.0.0.1]/", timeout=2)


def test_guarded_redirect_handler_vetoes_unsafe_location():
    # The redirect handler safe_urlopen installs re-checks each hop: a 302 whose Location is internal is
    # vetoed with SSRFBlocked instead of being followed (redirect/TOCTOU SSRF). Exercised directly.
    import urllib.request
    import pytest
    from services.safety.url_guard import _build_guarded_redirect_handler, SSRFBlocked

    handler = _build_guarded_redirect_handler()()
    req = urllib.request.Request("http://public.example/start")
    hdrs = urllib.message.Message() if hasattr(urllib, "message") else None
    import email.message
    hdrs = email.message.Message()
    # An unsafe redirect target is vetoed…
    with pytest.raises(SSRFBlocked):
        handler.redirect_request(req, None, 302, "Found", hdrs, "http://169.254.169.254/latest/meta-data/")
    # …a public redirect target is allowed through (returns a Request, does not raise).
    out = handler.redirect_request(req, None, 302, "Found", hdrs, "http://example.com/next")
    assert out is None or isinstance(out, urllib.request.Request)
