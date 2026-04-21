"""Phase 4.2 — retrieval confidence normalization tests."""
import pytest

from services.retrieval import (
    PLANNER_MIN_CONFIDENCE,
    _normalize_confidence,
    retrieve_high_confidence_memory,
    retrieve_relevant_memory,
)


def test_normalize_adds_confidence_from_adjusted():
    items = [{"content": "a", "adjusted_confidence": 0.8}]
    out = _normalize_confidence(items)
    assert out[0]["confidence"] == pytest.approx(0.8)


def test_normalize_defaults_to_half():
    items = [{"content": "b"}]
    out = _normalize_confidence(items)
    assert out[0]["confidence"] == pytest.approx(0.5)


def test_normalize_clamps_to_unit_interval():
    items = [
        {"content": "high", "confidence": 1.5},
        {"content": "low", "confidence": -0.3},
    ]
    out = _normalize_confidence(items)
    assert out[0]["confidence"] == pytest.approx(1.0)
    assert out[1]["confidence"] == pytest.approx(0.0)


def test_normalize_prefers_explicit_confidence():
    items = [{"content": "c", "confidence": 0.7, "adjusted_confidence": 0.2}]
    out = _normalize_confidence(items)
    assert out[0]["confidence"] == pytest.approx(0.7)


def test_planner_min_confidence_value():
    assert PLANNER_MIN_CONFIDENCE == 0.75


def test_retrieve_relevant_memory_min_confidence_filters(monkeypatch):
    fake = [
        {"content": "high", "confidence": 0.9},
        {"content": "low", "confidence": 0.3},
    ]
    monkeypatch.setattr(
        "services.retrieval._normalize_confidence",
        lambda items: items,
    )

    def _fake_retrieve(task, k=5, *, min_confidence=0.0):
        return [i for i in fake if i["confidence"] >= min_confidence]

    monkeypatch.setattr("services.retrieval.retrieve_relevant_memory", _fake_retrieve)
    from services.retrieval import retrieve_relevant_memory as rrm
    result = rrm("test", min_confidence=0.75)
    assert all(r["confidence"] >= 0.75 for r in result)


def test_retrieve_high_confidence_falls_back_when_scarce(monkeypatch):
    """If fewer than 2 high-confidence items, fallback returns all."""
    calls = []

    def _fake(task, k=5, *, min_confidence=0.0):
        calls.append(min_confidence)
        if min_confidence >= 0.75:
            return []  # simulate scarce
        return [{"content": "x", "confidence": 0.4}]

    monkeypatch.setattr("services.retrieval.retrieve_relevant_memory", _fake)
    from services.retrieval import retrieve_high_confidence_memory
    result = retrieve_high_confidence_memory("anything")
    # Should have called twice: once with min_confidence=0.75, once with 0.0
    assert 0.75 in calls
    assert 0.0 in calls
    assert len(result) > 0
