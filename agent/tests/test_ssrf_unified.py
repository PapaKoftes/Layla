"""The three duplicate _is_safe_url copies now delegate to the hardened url_guard,
so inputs the old prefix-checks let through (obfuscated-decimal IP, file://) are blocked.
Uses only literal/scheme cases so no DNS lookup is required."""
from __future__ import annotations

from install.model_downloader import _is_safe_url as downloader_safe
from layla.tools.web import _is_safe_url as web_safe
from services.infrastructure.browser import _is_safe_url as browser_safe


def test_all_three_block_decimal_encoded_loopback():
    # http://2130706433/ == http://127.0.0.1/ — old prefix-checks missed this.
    for fn in (web_safe, browser_safe, downloader_safe):
        assert fn("http://2130706433/") is False


def test_web_and_downloader_block_non_http_schemes():
    # web.py's old check had no scheme guard → file:// slipped through.
    assert web_safe("file:///etc/passwd") is False
    assert downloader_safe("file:///etc/passwd") is False


def test_public_host_literal_still_allowed():
    # A public IP literal needs no DNS and must still pass.
    for fn in (web_safe, browser_safe, downloader_safe):
        assert fn("http://93.184.216.34/") is True


def test_loopback_literal_blocked():
    for fn in (web_safe, browser_safe, downloader_safe):
        assert fn("http://127.0.0.1/") is False
        assert fn("http://192.168.1.10/") is False
