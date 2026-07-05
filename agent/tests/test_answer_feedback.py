"""BL-242: learning from feedback — 👍/👎 + corrections into the loop."""
from __future__ import annotations

import pytest

from services.infrastructure import answer_feedback as af


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(af, "_db_path", lambda: tmp_path / "fb.db")
    saved = []
    monkeypatch.setattr("layla.memory.learnings.save_learning",
                        lambda content, **kw: (saved.append((content, kw)) or 1), raising=False)
    return saved


def test_rating_validation():
    assert not af.record_feedback("meh")["ok"]
    assert af.record_feedback("up")["ok"]


def test_downvote_correction_routes_to_learning(_tmp):
    saved = _tmp
    r = af.record_feedback("down", goal="fix the bug", answer="wrong", correction="use a lock, not a flag")
    assert r["ok"] and r["routed_to_learning"] is True
    assert saved and "use a lock, not a flag" in saved[0][0]
    assert saved[0][1]["kind"] == "correction" and saved[0][1]["source"] == "user_feedback"


def test_downvote_without_correction_not_routed(_tmp):
    saved = _tmp
    r = af.record_feedback("down", answer="meh")
    assert r["ok"] and r["routed_to_learning"] is False
    assert saved == []


def test_upvote_not_routed(_tmp):
    saved = _tmp
    af.record_feedback("up", correction="ignored on upvote")
    assert saved == []


def test_stats():
    af.record_feedback("up")
    af.record_feedback("up")
    af.record_feedback("down", correction="be terser")
    s = af.feedback_stats()
    assert s["up"] == 2 and s["down"] == 1 and s["total"] == 3
    assert s["satisfaction"] == round(2 / 3, 3)
    assert s["corrections_routed"] == 1


def test_hint_surfaces_recent_corrections():
    assert af.feedback_hint_for_prompt() == ""
    af.record_feedback("down", correction="prefer tables over prose")
    hint = af.feedback_hint_for_prompt()
    assert "prefer tables over prose" in hint and "honour going forward" in hint
