# -*- coding: utf-8 -*-
"""
test_memory_commands.py -- Unit tests for memory command interception and working memory.

Tests the memory_commands.detect_and_handle() dispatcher and
working_memory.py CRUD without requiring a real DB or LLM.

Run:
    cd agent/ && python -m pytest tests/test_memory_commands.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ---------------------------------------------------------------------------
# memory_commands -- basic pattern matching (no DB)
# ---------------------------------------------------------------------------

from services.memory_commands import MemoryCommandResult, detect_and_handle


def test_non_command_passthrough():
    r = detect_and_handle("what is the meaning of life")
    assert r.is_command is False
    assert r.response == ""


def test_non_command_empty():
    r = detect_and_handle("")
    assert r.is_command is False


def test_remember_too_short():
    r = detect_and_handle("remember: hi")
    assert r.is_command is True
    assert r.error == "too_short"
    assert r.command == "remember"


def test_remember_triggers_pattern():
    """Pattern matched -- DB call will fail without DB, but is_command must be True."""
    with patch("layla.memory.db.save_learning", return_value=42), \
         patch("services.working_memory.add_to_working_memory", return_value=None):
        r = detect_and_handle("remember: my favorite language is Python")
    assert r.is_command is True
    assert r.command == "remember"
    assert r.items_affected == 1
    assert "Python" in r.response or "Stored" in r.response


def test_remember_aliases():
    """memorize, note, store, save all trigger remember."""
    for verb in ("memorize", "note", "store", "save"):
        msg = f"{verb}: the user prefers concise responses"
        with patch("layla.memory.db.save_learning", return_value=1), \
             patch("services.working_memory.add_to_working_memory", return_value=None):
            r = detect_and_handle(msg)
        assert r.is_command is True, f"{verb} should trigger remember"
        assert r.command == "remember"


def test_forget_no_content():
    r = detect_and_handle("forget:")
    # Regex won't match empty capture -- falls through to non-command
    assert r.is_command is False or (r.is_command and "what" in r.response.lower())


def test_forget_finds_nothing():
    with patch("layla.memory.db.search_learnings_fts", return_value=[]), \
         patch("layla.memory.db.get_recent_learnings", return_value=[]):
        r = detect_and_handle("forget: nonexistent topic xyz")
    assert r.is_command is True
    assert r.command == "forget"
    assert r.items_affected == 0
    assert "Nothing found" in r.response


def test_forget_deletes_matches():
    mock_rows = [
        {"id": "1", "content": "Python is my favorite language"},
        {"id": "2", "content": "Python for data science"},
    ]
    with patch("layla.memory.db.search_learnings_fts", return_value=mock_rows), \
         patch("layla.memory.db.delete_learnings_by_id", return_value=None):
        r = detect_and_handle("forget: Python")
    assert r.is_command is True
    assert r.command == "forget"
    assert r.items_affected == 2


def test_recall_empty():
    r = detect_and_handle("recall:")
    # Empty capture -- likely won't match the regex
    assert r.is_command is False or "what" in r.response.lower()


def test_recall_returns_results():
    mock_rows = [
        {"content": "Python is great for scripting", "confidence": 0.9},
        {"content": "Use virtual environments", "confidence": 0.8},
    ]
    with patch("layla.memory.vector_store.search_memories_full", return_value=mock_rows):
        r = detect_and_handle("recall: Python")
    assert r.is_command is True
    assert r.command == "recall"
    assert r.items_affected == 2
    assert "Python" in r.response


def test_recall_falls_back_to_fts():
    """When vector store fails, falls back to FTS search."""
    mock_rows = [{"content": "Python is great", "confidence": 0.7}]
    with patch("layla.memory.vector_store.search_memories_full", side_effect=Exception("no vector store")), \
         patch("layla.memory.db.search_learnings_fts", return_value=mock_rows):
        r = detect_and_handle("recall: Python")
    assert r.is_command is True
    assert r.items_affected == 1


def test_recall_nothing_found():
    with patch("layla.memory.vector_store.search_memories_full", return_value=[]), \
         patch("layla.memory.db.search_learnings_fts", return_value=[]):
        r = detect_and_handle("recall: absolutely nothing here xyz999")
    assert r.is_command is True
    assert r.items_affected == 0
    assert "Nothing found" in r.response


def test_status_command():
    with patch("layla.memory.db.count_learnings", return_value=42), \
         patch("layla.memory.db.get_recent_learnings", return_value=[{"content": "a fact"}]):
        r = detect_and_handle("memory status")
    assert r.is_command is True
    assert r.command == "status"
    assert "42" in r.response


def test_status_aliases():
    for phrase in ("memory stats", "memory summary", "memory count", "memory how many"):
        with patch("layla.memory.db.count_learnings", return_value=0), \
             patch("layla.memory.db.get_recent_learnings", return_value=[]):
            r = detect_and_handle(phrase)
        assert r.is_command is True, f"'{phrase}' should trigger status"


def test_clear_requires_confirm():
    r = detect_and_handle("memory clear")
    assert r.is_command is True
    assert r.command == "clear"
    assert "--confirm" in r.response


def test_clear_with_confirm():
    mock_conn = MagicMock()
    mock_conn.execute.return_value.rowcount = 5
    with patch("layla.memory.db._conn", return_value=mock_conn):
        r = detect_and_handle("memory clear --confirm")
    assert r.is_command is True
    assert r.items_affected == 5


def test_layla_prefix_accepted():
    """'layla, remember: X' should work."""
    with patch("layla.memory.db.save_learning", return_value=1), \
         patch("services.working_memory.add_to_working_memory", return_value=None):
        r = detect_and_handle("layla, remember: I work in Python and C++")
    assert r.is_command is True


def test_remember_rate_limited():
    with patch("layla.memory.db.save_learning", return_value=-1):
        r = detect_and_handle("remember: this is a perfectly fine long fact about something important")
    assert r.is_command is True
    assert r.error == "rate_limited"


# ---------------------------------------------------------------------------
# working_memory -- in-memory operations (no disk I/O)
# ---------------------------------------------------------------------------

def test_wm_add_and_get(tmp_path):
    import services.working_memory as wm
    # Redirect to temp path
    _orig = wm._WM_PATH
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.add_to_working_memory("user prefers dark mode")
        data = wm.get_working_memory()
        assert "user prefers dark mode" in data["recent_facts"]
    finally:
        wm._WM_PATH = _orig
        wm._cache = None


def test_wm_dedup(tmp_path):
    import services.working_memory as wm
    _orig = wm._WM_PATH
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.add_to_working_memory("user likes Python")
        wm.add_to_working_memory("user likes Python")
        data = wm.get_working_memory()
        assert data["recent_facts"].count("user likes Python") == 1
    finally:
        wm._WM_PATH = _orig
        wm._cache = None


def test_wm_fifo_cap(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        for i in range(25):
            wm.add_to_working_memory(f"fact number {i:04d} about something long enough")
        data = wm.get_working_memory()
        assert len(data["recent_facts"]) <= wm._MAX_FACTS
        # Most recent facts should be present
        assert any("0024" in f for f in data["recent_facts"])
    finally:
        wm._cache = None


def test_wm_set_project_and_action(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.set_active_project("local-jinx-agent memory system")
        wm.set_next_action("wire memory commands into agent loop")
        data = wm.get_working_memory()
        assert data["active_project"] == "local-jinx-agent memory system"
        assert data["next_action"] == "wire memory commands into agent loop"
    finally:
        wm._cache = None


def test_wm_blockers(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.add_blocker("chroma not installed")
        wm.add_blocker("missing DB migration")
        data = wm.get_working_memory()
        assert "chroma not installed" in data["blockers"]
        assert "missing DB migration" in data["blockers"]
        removed = wm.clear_blocker("chroma")
        assert removed == 1
        data2 = wm.get_working_memory()
        assert "chroma not installed" not in data2["blockers"]
        assert "missing DB migration" in data2["blockers"]
    finally:
        wm._cache = None


def test_wm_reset(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.set_active_project("test project")
        wm.reset()
        data = wm.get_working_memory()
        assert data["active_project"] == ""
        assert data["recent_facts"] == []
    finally:
        wm._cache = None


def test_wm_format_for_prompt_empty(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.reset()
        result = wm.format_for_prompt()
        assert result == ""
    finally:
        wm._cache = None


def test_wm_format_for_prompt_populated(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.reset()
        wm.set_active_project("memory system refactor")
        wm.set_next_action("write tests")
        wm.add_blocker("need DB fixture")
        wm.add_to_working_memory("user is building local AI agent")
        result = wm.format_for_prompt()
        assert "memory system refactor" in result
        assert "write tests" in result
        assert "need DB fixture" in result
        assert "local AI agent" in result
        assert "[Working memory" in result
    finally:
        wm._cache = None


def test_wm_auto_extract_project(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.reset()
        wm.auto_extract_from_message("I am working on the memory system for the agent")
        data = wm.get_working_memory()
        # Pattern match should set active_project
        assert data["active_project"] != ""
    finally:
        wm._cache = None


def test_wm_auto_extract_blocker(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.reset()
        wm.auto_extract_from_message("I am stuck on the DB migration issue right now")
        data = wm.get_working_memory()
        assert len(data["blockers"]) > 0
    finally:
        wm._cache = None


def test_wm_short_message_ignored(tmp_path):
    import services.working_memory as wm
    wm._WM_PATH = tmp_path / ".layla" / "working_memory.json"
    wm._cache = None
    try:
        wm.reset()
        wm.auto_extract_from_message("hi")
        data = wm.get_working_memory()
        assert data["active_project"] == ""
    finally:
        wm._cache = None
