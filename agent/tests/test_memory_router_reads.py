"""Tests for the read-path delegation functions in services.memory_router."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

_DB_MODULE = "layla.memory.db"


# ── 1. get_recent_learnings delegates ─────────────────────────────────────────

def test_get_recent_learnings_delegates():
    from services import memory_router as mr

    sentinel = [{"id": 1, "content": "hello"}]
    with patch(f"{_DB_MODULE}.get_recent_learnings", return_value=sentinel) as mock:
        result = mr.get_recent_learnings(n=5)

    mock.assert_called_once_with(n=5)
    assert result is sentinel


# ── 2. search_learnings_fts delegates ─────────────────────────────────────────

def test_search_learnings_fts_delegates():
    from services import memory_router as mr

    sentinel = [{"id": 2, "content": "match"}]
    with patch(f"{_DB_MODULE}.search_learnings_fts", return_value=sentinel) as mock:
        result = mr.search_learnings_fts("test query", limit=10)

    mock.assert_called_once_with("test query", limit=10)
    assert result is sentinel


# ── 3. count_learnings delegates ──────────────────────────────────────────────

def test_count_learnings_delegates():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.count_learnings", return_value=42) as mock:
        result = mr.count_learnings()

    mock.assert_called_once_with()
    assert result == 42


# ── 4. get_aspect_memories delegates ──────────────────────────────────────────

def test_get_aspect_memories_delegates():
    from services import memory_router as mr

    sentinel = [{"aspect": "coding", "content": "tip"}]
    with patch(f"{_DB_MODULE}.get_aspect_memories", return_value=sentinel) as mock:
        result = mr.get_aspect_memories("coding", n=3)

    mock.assert_called_once_with("coding", 3)
    assert result is sentinel


# ── 5. get_user_identity delegates ────────────────────────────────────────────

def test_get_user_identity_delegates():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.get_user_identity", return_value="Alice") as mock:
        result = mr.get_user_identity("name")

    mock.assert_called_once_with("name")
    assert result == "Alice"


# ── 6. set_user_identity delegates ────────────────────────────────────────────

def test_set_user_identity_delegates():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.set_user_identity") as mock:
        mr.set_user_identity("name", "Bob")

    mock.assert_called_once_with("name", "Bob")


# ── 7. get_all_user_identity delegates ────────────────────────────────────────

def test_get_all_user_identity_delegates():
    from services import memory_router as mr

    sentinel = {"name": "Alice", "lang": "en"}
    with patch(f"{_DB_MODULE}.get_all_user_identity", return_value=sentinel) as mock:
        result = mr.get_all_user_identity()

    mock.assert_called_once_with()
    assert result is sentinel


# ── 8. delete_learnings_by_id delegates ───────────────────────────────────────

def test_delete_learnings_by_id_delegates():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.delete_learnings_by_id", return_value=3) as mock:
        result = mr.delete_learnings_by_id([10, 20, 30])

    mock.assert_called_once_with([10, 20, 30])
    assert result == 3


# ── 9. Graceful handling when db import fails ────────────────────────────────

def test_read_functions_handle_import_error():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.get_recent_learnings", side_effect=ImportError("no db")):
        assert mr.get_recent_learnings() == []

    with patch(f"{_DB_MODULE}.search_learnings_fts", side_effect=ImportError("no db")):
        assert mr.search_learnings_fts("q") == []

    with patch(f"{_DB_MODULE}.count_learnings", side_effect=ImportError("no db")):
        assert mr.count_learnings() == 0

    with patch(f"{_DB_MODULE}.get_aspect_memories", side_effect=ImportError("no db")):
        assert mr.get_aspect_memories("x") == []

    with patch(f"{_DB_MODULE}.get_user_identity", side_effect=ImportError("no db")):
        assert mr.get_user_identity("k") is None

    with patch(f"{_DB_MODULE}.set_user_identity", side_effect=ImportError("no db")):
        mr.set_user_identity("k", "v")  # should not raise

    with patch(f"{_DB_MODULE}.get_all_user_identity", side_effect=ImportError("no db")):
        assert mr.get_all_user_identity() == {}

    with patch(f"{_DB_MODULE}.delete_learnings_by_id", side_effect=ImportError("no db")):
        assert mr.delete_learnings_by_id([1]) == 0


# ── 10. Graceful handling when db function raises ────────────────────────────

def test_read_functions_handle_exception():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.get_recent_learnings", side_effect=RuntimeError("boom")):
        assert mr.get_recent_learnings() == []

    with patch(f"{_DB_MODULE}.search_learnings_fts", side_effect=RuntimeError("boom")):
        assert mr.search_learnings_fts("q") == []

    with patch(f"{_DB_MODULE}.count_learnings", side_effect=RuntimeError("boom")):
        assert mr.count_learnings() == 0

    with patch(f"{_DB_MODULE}.get_aspect_memories", side_effect=RuntimeError("boom")):
        assert mr.get_aspect_memories("x") == []

    with patch(f"{_DB_MODULE}.get_user_identity", side_effect=RuntimeError("boom")):
        assert mr.get_user_identity("k") is None

    with patch(f"{_DB_MODULE}.set_user_identity", side_effect=RuntimeError("boom")):
        mr.set_user_identity("k", "v")  # should not raise

    with patch(f"{_DB_MODULE}.get_all_user_identity", side_effect=RuntimeError("boom")):
        assert mr.get_all_user_identity() == {}

    with patch(f"{_DB_MODULE}.delete_learnings_by_id", side_effect=RuntimeError("boom")):
        assert mr.delete_learnings_by_id([1]) == 0


# ── 11. Conversation helpers delegation ────────────────────────────────────────

def test_create_conversation_delegates():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.create_conversation", return_value="conv-1") as mock:
        result = mr.create_conversation(conversation_id="conv-1", title="Test")

    mock.assert_called_once_with(conversation_id="conv-1", title="Test")
    assert result == "conv-1"


def test_create_conversation_fallback():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.create_conversation", side_effect=RuntimeError("boom")):
        assert mr.create_conversation(conversation_id="conv-1") == "conv-1"


def test_append_conversation_message_delegates():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.append_conversation_message") as mock:
        mr.append_conversation_message("conv-1", "user", "hello")

    mock.assert_called_once_with("conv-1", "user", "hello")


def test_append_conversation_message_error_safe():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.append_conversation_message", side_effect=RuntimeError("boom")):
        mr.append_conversation_message("conv-1", "user", "hello")  # should not raise


def test_get_conversation_messages_delegates():
    from services import memory_router as mr

    sentinel = [{"role": "user", "content": "hi"}]
    with patch(f"{_DB_MODULE}.get_conversation_messages", return_value=sentinel) as mock:
        result = mr.get_conversation_messages("conv-1", limit=10)

    mock.assert_called_once_with("conv-1", limit=10)
    assert result is sentinel


def test_get_conversation_messages_error_safe():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.get_conversation_messages", side_effect=RuntimeError("boom")):
        assert mr.get_conversation_messages("conv-1") == []


def test_get_conversation_delegates():
    from services import memory_router as mr

    sentinel = {"id": "conv-1", "title": "Test"}
    with patch(f"{_DB_MODULE}.get_conversation", return_value=sentinel) as mock:
        result = mr.get_conversation("conv-1")

    mock.assert_called_once_with("conv-1")
    assert result is sentinel


def test_get_conversation_error_safe():
    from services import memory_router as mr

    with patch(f"{_DB_MODULE}.get_conversation", side_effect=RuntimeError("boom")):
        assert mr.get_conversation("conv-1") is None
