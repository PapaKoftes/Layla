"""Elasticsearch bridge behavior when optional deps/server are absent."""

from __future__ import annotations

from services.elasticsearch_bridge import search_learnings


def test_search_returns_disabled_when_es_off():
    out = search_learnings({"elasticsearch_enabled": False}, "hello", limit=5)
    assert out.get("ok") is False
    assert out.get("error") == "elasticsearch_disabled"
    assert out.get("hits") == []
