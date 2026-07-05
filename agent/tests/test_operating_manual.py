"""BL-236: personal operating manual — derived identity + living user notes."""
from __future__ import annotations

import pytest

from services.personality import operating_manual as om


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(om, "_db_path", lambda: tmp_path / "manual.db")
    monkeypatch.setattr(om, "_identity", lambda: {
        "verbosity": "concise", "formality": "casual", "humor_tolerance": "high",
    })
    monkeypatch.setattr(om, "_profile", lambda: {"work_domains": ["ai", "backend"], "stats": {"grit": 8}})


def test_notes_crud():
    r = om.add_note("habit", "commits after every stage")
    assert r["ok"] and r["category"] == "habit"
    assert not om.add_note("habit", "")["ok"]
    assert om.add_note("weird", "x")["category"] == "other"   # unknown → other
    notes = om.list_notes()
    assert len(notes) == 2
    assert om.delete_note(r["id"])["ok"]
    assert len(om.list_notes()) == 1


def test_build_manual_combines_sources():
    om.add_note("workflow", "plan → build → verify → commit")
    m = om.build_manual()
    assert m["identity"]["Verbosity"] == "concise"
    assert m["identity"]["Humour"] == "high"
    assert m["work_domains"] == ["ai", "backend"]
    assert m["notes"]["workflow"] == ["plan → build → verify → commit"]


def test_markdown_sections():
    om.add_note("habit", "tests before push")
    md = om.manual_markdown()
    assert "## Style" in md and "**Verbosity:** concise" in md
    assert "## Work domains" in md and "ai, backend" in md
    assert "## Habits & workflows" in md and "tests before push" in md


def test_prompt_digest_is_bounded():
    om.add_note("preference", "no emoji")
    s = om.manual_for_prompt(max_chars=200)
    assert "verbosity=concise" in s and "domains:" in s and "no emoji" in s
    assert len(s) <= 200


def test_empty_manual_message(monkeypatch):
    monkeypatch.setattr(om, "_identity", lambda: {})
    monkeypatch.setattr(om, "_profile", lambda: {})
    assert "fills in as Layla learns" in om.manual_markdown()
