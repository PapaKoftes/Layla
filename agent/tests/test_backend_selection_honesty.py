# -*- coding: utf-8 -*-
"""vector_backend / search_backend must never be SILENT config lies.

qdrant + the external search engines are complete modules but aren't dispatched into the core
memory/recall paths. Rather than pretend the selection took effect, startup validation warns.
"""
from __future__ import annotations

import runtime_safety as rs


def test_default_backends_are_silent():
    assert rs.validate_backend_selection({"vector_backend": "chroma", "search_backend": "auto"}) == []
    assert rs.validate_backend_selection({}) == []


def test_qdrant_selection_is_flagged():
    msgs = rs.validate_backend_selection({"vector_backend": "qdrant"})
    assert any("vector_backend" in m and "qdrant" in m for m in msgs)


def test_external_search_backend_is_flagged():
    for be in ("meilisearch", "elasticsearch"):
        msgs = rs.validate_backend_selection({"search_backend": be})
        assert any("search_backend" in m and be in m for m in msgs)
    # sqlite_fts is effectively the direct path — no warning.
    assert rs.validate_backend_selection({"search_backend": "sqlite_fts"}) == []
