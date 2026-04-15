from __future__ import annotations


def test_journal_add_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYLA_DB_PATH", str(tmp_path / "layla.db"))

    from layla.memory.db import add_journal_entry, list_journal_entries

    r = add_journal_entry("note", "hello", tags="a,b", project_id="p1", aspect_id="nyx", conversation_id="c1")
    assert r["ok"] is True
    entries = list_journal_entries(limit=10)
    assert entries
    assert entries[0]["content"] == "hello"
    assert entries[0]["tags"] == "a,b"

