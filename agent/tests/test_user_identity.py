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


# ── Durable facts (the RAG split: hard identity facts, injected verbatim) ──

def test_durable_fact_keys_are_in_whitelist():
    # The update_user_identity_tool validates against USER_IDENTITY_KEYS; the
    # durable keys must be accepted there or the model could never save them.
    for k in ("name", "timezone", "indent_style", "project_roots"):
        assert k in up.USER_IDENTITY_KEYS


def test_get_durable_facts_returns_present_keys_ordered_and_labelled():
    up.set_user_identity("timezone", "Europe/Berlin")
    up.set_user_identity("name", "Mina")
    facts = up.get_durable_facts()
    labels = [label for label, _ in facts]
    # Present facts only, ordered per DURABLE_FACT_KEYS (name before timezone).
    assert ("Name", "Mina") in facts
    assert ("Timezone", "Europe/Berlin") in facts
    assert labels.index("Name") < labels.index("Timezone")
    # A style key must NOT leak into durable facts.
    assert "Verbosity" not in labels


def test_get_durable_facts_skips_empty_values():
    up.set_user_identity("editor", "")
    facts = dict(up.get_durable_facts())
    assert "Preferred editor" not in facts


def test_durable_facts_injected_verbatim_into_system_head():
    from services.prompts import system_head_builder as shb

    up.set_user_identity("name", "Mina")
    up.set_user_identity("indent_style", "spaces (4)")
    head = shb.build_system_head(goal="hello", aspect=None)
    text = head if isinstance(head, str) else str(head)
    assert "Durable facts about the user" in text
    assert "Mina" in text and "spaces (4)" in text
