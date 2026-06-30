"""Tests for user-identity read/forget (layla/memory/user_profile.py).

Covers a regression: get_all_user_identity() called r.get("key") on a
sqlite3.Row, which has no .get() — so it threw whenever the table had rows.
DB is auto-isolated to a tmp dir by the session-scoped conftest fixture.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.memory import user_profile as up  # noqa: E402


def test_get_all_user_identity_does_not_raise_with_rows():
    # Regression: a populated user_identity table must not raise.
    up.set_user_identity("verbosity", "concise")
    result = up.get_all_user_identity()  # must not raise
    assert isinstance(result, dict)
    assert result.get("verbosity") == "concise"


def test_identity_set_get_delete_roundtrip():
    up.set_user_identity("humor_tolerance", "high")
    assert up.get_all_user_identity().get("humor_tolerance") == "high"
    assert up.delete_user_identity("humor_tolerance") is True
    assert "humor_tolerance" not in up.get_all_user_identity()
    # deleting an absent / empty key is a clean no-op
    assert up.delete_user_identity("humor_tolerance") is False
    assert up.delete_user_identity("") is False
    assert up.delete_user_identity("   ") is False
