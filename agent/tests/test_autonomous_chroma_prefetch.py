"""Tests for Tier-0 Chroma learnings prefetch (read-only)."""

from __future__ import annotations

from unittest.mock import patch

from autonomous.chroma_retrieval import try_chroma_retrieval


def test_try_chroma_retrieval_disabled_returns_none():
    cfg = {
        "autonomous_chroma_enabled": False,
        "use_chroma": True,
    }
    assert try_chroma_retrieval("analyze the codebase architecture", "/tmp/ws", cfg) is None


def test_try_chroma_retrieval_use_chroma_false_returns_none():
    cfg = {
        "autonomous_chroma_enabled": True,
        "use_chroma": False,
    }
    assert try_chroma_retrieval("analyze the codebase architecture", "/tmp/ws", cfg) is None


def test_try_chroma_retrieval_below_threshold_returns_none():
    cfg = {
        "autonomous_chroma_enabled": True,
        "use_chroma": True,
        "autonomous_chroma_match_threshold": 0.99,
        "autonomous_chroma_top_k": 3,
    }
    with patch("autonomous.chroma_retrieval.query_learnings_best_similarity", return_value=(0.5, {"content": "x"})):
        assert try_chroma_retrieval("goal text here", "/tmp/ws", cfg) is None


def test_try_chroma_retrieval_hit_returns_payload():
    cfg = {
        "autonomous_chroma_enabled": True,
        "use_chroma": True,
        "autonomous_chroma_match_threshold": 0.75,
        "autonomous_chroma_top_k": 3,
    }
    with patch(
        "autonomous.chroma_retrieval.query_learnings_best_similarity",
        return_value=(0.91, {"content": "Prior learning about imports.", "embedding_id": "abc-1"}),
    ):
        hit = try_chroma_retrieval("goal text here", "/tmp/ws", cfg)
    assert hit is not None
    assert hit["summary"]
    assert hit["findings"]
    assert hit["confidence"] == "medium"
    assert hit["embedding_id"] == "abc-1"
    assert hit["match_score"] == 0.91


def test_query_learnings_best_similarity_returns_none_when_empty(monkeypatch):
    from layla.memory import vector_store as vs

    def fake_chroma():
        return False

    monkeypatch.setattr(vs, "_use_chroma", fake_chroma)
    assert vs.query_learnings_best_similarity("hello", top_k=3) is None
