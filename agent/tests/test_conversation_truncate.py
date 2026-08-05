"""Backend for the 'edit an earlier message' flow: truncate a conversation from a message onward.

The UI edits a user message, then removes that message + everything downstream and resends the
edited text as a fresh turn. The server side is truncate_conversation_from — delete the target
message and all later messages, keeping the clean prefix.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from layla.memory.db import (
    append_conversation_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_conversation_messages,
    truncate_conversation_from,
)


def _seed():
    cid = "trunc-test-" + uuid.uuid4().hex[:8]
    create_conversation(cid, title="trunc-test")
    for role, txt in [
        ("user", "u1"), ("assistant", "a1"),
        ("user", "u2"), ("assistant", "a2"),
        ("user", "u3"), ("assistant", "a3"),
    ]:
        append_conversation_message(cid, role, txt)
    return cid


def test_truncate_removes_target_and_everything_after():
    cid = _seed()
    try:
        msgs = get_conversation_messages(cid, limit=100)
        u2 = next(m for m in msgs if m["content"] == "u2")
        removed = truncate_conversation_from(cid, u2["id"])
        assert removed == 4  # u2, a2, u3, a3
        after = [m["content"] for m in get_conversation_messages(cid, limit=100)]
        assert after == ["u1", "a1"]
        # message_count is kept in sync so the sidebar / budgeting stay correct
        assert int(get_conversation(cid).get("message_count", -1)) == 2
    finally:
        delete_conversation(cid)


def test_truncate_from_first_message_clears_all():
    cid = _seed()
    try:
        first = get_conversation_messages(cid, limit=100)[0]
        removed = truncate_conversation_from(cid, first["id"])
        assert removed == 6
        assert get_conversation_messages(cid, limit=100) == []
    finally:
        delete_conversation(cid)


def test_truncate_unknown_message_is_a_noop():
    cid = _seed()
    try:
        assert truncate_conversation_from(cid, "does-not-exist") == 0
        assert len(get_conversation_messages(cid, limit=100)) == 6
    finally:
        delete_conversation(cid)


def test_truncate_unknown_conversation_is_a_noop():
    assert truncate_conversation_from("no-such-conversation", "whatever") == 0


def test_truncate_requires_ids():
    assert truncate_conversation_from("", "x") == 0
    assert truncate_conversation_from("x", "") == 0
