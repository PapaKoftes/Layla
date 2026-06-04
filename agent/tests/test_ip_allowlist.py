"""Tests for is_ip_allowed (services/tunnel_auth.py).

Regression for the post-remediation finding: the previous "localhost is always
allowed regardless of allowlist" short-circuit let a token-holder bypass the IP
allowlist by spoofing X-Forwarded-For: 127.0.0.1. is_ip_allowed is only reached
for REMOTE requests, so loopback must NOT be auto-allowed against a set allowlist.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.tunnel_auth import is_ip_allowed  # noqa: E402


def test_empty_allowlist_allows_all():
    assert is_ip_allowed("8.8.8.8", {}) is True
    assert is_ip_allowed("8.8.8.8", {"tunnel_ip_allowlist": []}) is True


def test_loopback_not_auto_allowed_against_allowlist():
    cfg = {"tunnel_ip_allowlist": ["203.0.113.0/24"]}
    # spoofed loopback must NOT bypass the allowlist
    assert is_ip_allowed("127.0.0.1", cfg) is False
    assert is_ip_allowed("::1", cfg) is False
    assert is_ip_allowed("localhost", cfg) is False


def test_allowlist_match_and_miss():
    cfg = {"tunnel_ip_allowlist": ["203.0.113.0/24", "198.51.100.7"]}
    assert is_ip_allowed("203.0.113.9", cfg) is True   # CIDR match
    assert is_ip_allowed("198.51.100.7", cfg) is True  # exact match
    assert is_ip_allowed("8.8.8.8", cfg) is False      # miss
    assert is_ip_allowed("", cfg) is False             # no ip
    assert is_ip_allowed("garbage", cfg) is False      # unparseable
