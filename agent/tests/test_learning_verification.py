"""BL-192: memory/learning verification — contradiction detection + pass."""
from __future__ import annotations

from services.memory import learning_verification as lv


def test_polarity():
    assert lv._polarity("the user prefers dark mode") == 1
    assert lv._polarity("the user does not want dark mode") == -1
    assert lv._polarity("dark mode exists") == 0


def test_find_contradictions_flags_opposite_polarity():
    learnings = [
        {"id": 1, "content": "The user prefers dark mode terminal themes"},
        {"id": 2, "content": "The user does not want dark mode terminal themes"},
        {"id": 3, "content": "The project uses fastapi and sqlite"},
    ]
    c = lv.find_contradictions(learnings, min_overlap=2)
    assert len(c) == 1
    pair = c[0]
    assert {pair["a_id"], pair["b_id"]} == {1, 2}
    assert "mode" in pair["shared_terms"] or "terminal" in pair["shared_terms"]


def test_no_false_contradiction_same_polarity():
    learnings = [
        {"id": 1, "content": "The user prefers concise answers always"},
        {"id": 2, "content": "The user prefers concise code comments always"},
    ]
    assert lv.find_contradictions(learnings, min_overlap=2) == []


def test_run_pass_reports(monkeypatch):
    fake = [
        {"id": 1, "content": "user wants the emoji picker enabled", "confidence": 0.6, "adjusted_confidence": 0.4},
        {"id": 2, "content": "user does not want the emoji picker enabled", "confidence": 0.6, "adjusted_confidence": 0.6},
    ]
    monkeypatch.setattr("layla.memory.learnings.get_recent_learnings", lambda n=200: fake)
    monkeypatch.setattr("layla.memory.learnings.get_learnings_due_for_review", lambda limit=100: [1])
    monkeypatch.setattr(
        "services.memory.memory_consolidation.prune_low_confidence_learnings",
        lambda threshold=0.08: 3,
    )
    r = lv.run_verification_pass()
    assert r["reviewed"] == 2
    assert r["decayed"] == 1            # learning 1's adjusted < confidence
    assert r["pruned"] == 3
    assert r["due_for_review"] == 1
    assert r["contradiction_count"] == 1


def test_run_pass_prune_disabled(monkeypatch):
    monkeypatch.setattr("layla.memory.learnings.get_recent_learnings", lambda n=200: [])
    monkeypatch.setattr("layla.memory.learnings.get_learnings_due_for_review", lambda limit=100: [])
    r = lv.run_verification_pass(prune=False)
    assert r["pruned"] == 0 and r["reviewed"] == 0
