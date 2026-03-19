"""Tests for transports/base inbound gate (no Layla server)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transports import base as tb


@pytest.fixture
def isolated_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "_REPO_ROOT", tmp_path)
    return tmp_path


def test_parse_id_list():
    assert tb._parse_id_list("") == set()
    assert tb._parse_id_list("a, b  c") == {"a", "b", "c"}


def test_allowlist_allows_matching_id(isolated_repo_root, monkeypatch):
    monkeypatch.setattr(
        tb,
        "get_inbound_transport_security",
        lambda: {
            "allowlist": {"99", "telegram:100"},
            "pairing_secret": "",
            "transport_require_allowlist": False,
            "misconfigured": False,
        },
    )
    assert tb.check_transport_inbound("telegram", "99", "hi")[0] is True
    assert tb.check_transport_inbound("telegram", "100", "hi")[0] is True
    assert tb.check_transport_inbound("telegram", "101", "hi")[0] is False


def test_pairing_then_chat(isolated_repo_root, monkeypatch):
    monkeypatch.setattr(
        tb,
        "get_inbound_transport_security",
        lambda: {
            "allowlist": set(),
            "pairing_secret": "sekret",
            "transport_require_allowlist": False,
            "misconfigured": False,
        },
    )
    ok, msg = tb.check_transport_inbound("slack", "7", "/pair wrong")
    assert ok is False and msg and "Invalid" in msg

    ok, msg = tb.check_transport_inbound("slack", "7", "/pair sekret")
    assert ok is False and msg and "Paired" in msg

    assert tb.check_transport_inbound("slack", "7", "hello")[0] is True


def test_misconfigured_denies_all(monkeypatch):
    monkeypatch.setattr(
        tb,
        "get_inbound_transport_security",
        lambda: {
            "allowlist": set(),
            "pairing_secret": "",
            "transport_require_allowlist": True,
            "misconfigured": True,
        },
    )
    ok, msg = tb.check_transport_inbound("telegram", "1", "hi")
    assert ok is False and msg and "misconfigured" in msg.lower()
