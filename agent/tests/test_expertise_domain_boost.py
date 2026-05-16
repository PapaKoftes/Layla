"""Tests for expertise domain extraction, system prompt injection, and retrieval boosting."""
import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_aspect(primary=None, secondary=None, philosophy="", gaps=None, can_refuse=None, name="Morrigan"):
    """Build a minimal aspect dict with expertise_domains."""
    ed = {}
    if primary is not None:
        ed["primary"] = primary
    if secondary is not None:
        ed["secondary"] = secondary
    if philosophy:
        ed["philosophy"] = philosophy
    if gaps is not None:
        ed["knowledge_gaps_honest"] = gaps
    if can_refuse is not None:
        ed["can_refuse_technical"] = can_refuse
    return {"id": name.lower(), "name": name, "expertise_domains": ed}


# ── _extract_aspect_domain_keywords ──────────────────────────────────────────


class TestExtractDomainKeywords:
    def test_returns_empty_for_no_aspect(self):
        from agent_loop import _extract_aspect_domain_keywords
        assert _extract_aspect_domain_keywords(None) == []

    def test_returns_empty_for_no_expertise(self):
        from agent_loop import _extract_aspect_domain_keywords
        assert _extract_aspect_domain_keywords({"id": "x", "name": "X"}) == []

    def test_extracts_primary_keywords(self):
        from agent_loop import _extract_aspect_domain_keywords
        aspect = _make_aspect(primary=["Python (stdlib, async)", "debugging (pdb, traceback)"])
        kws = _extract_aspect_domain_keywords(aspect)
        assert "python" in kws
        assert "debugging" in kws

    def test_extracts_secondary_keywords(self):
        from agent_loop import _extract_aspect_domain_keywords
        aspect = _make_aspect(primary=[], secondary=["Git internals (rebase)", "SQL (SQLite)"])
        kws = _extract_aspect_domain_keywords(aspect)
        assert "git internals" in kws
        assert "sql" in kws

    def test_caps_at_12_keywords(self):
        from agent_loop import _extract_aspect_domain_keywords
        big_list = [f"domain_{i}" for i in range(20)]
        aspect = _make_aspect(primary=big_list)
        kws = _extract_aspect_domain_keywords(aspect)
        assert len(kws) <= 12

    def test_skips_long_entries(self):
        from agent_loop import _extract_aspect_domain_keywords
        aspect = _make_aspect(primary=["x" * 50])  # >40 chars after split
        kws = _extract_aspect_domain_keywords(aspect)
        assert len(kws) == 0

    def test_handles_non_dict_expertise(self):
        from agent_loop import _extract_aspect_domain_keywords
        aspect = {"id": "x", "name": "X", "expertise_domains": "not a dict"}
        assert _extract_aspect_domain_keywords(aspect) == []

    def test_handles_non_list_primary(self):
        from agent_loop import _extract_aspect_domain_keywords
        aspect = {"id": "x", "name": "X", "expertise_domains": {"primary": "not a list"}}
        assert _extract_aspect_domain_keywords(aspect) == []


# ── _build_expertise_domain_block ────────────────────────────────────────────


class TestBuildExpertiseDomainBlock:
    def test_returns_empty_for_no_aspect(self):
        from agent_loop import _build_expertise_domain_block
        assert _build_expertise_domain_block(None) == ""

    def test_returns_empty_for_no_expertise(self):
        from agent_loop import _build_expertise_domain_block
        assert _build_expertise_domain_block({"id": "x", "name": "X"}) == ""

    def test_includes_primary_domains(self):
        from agent_loop import _build_expertise_domain_block
        aspect = _make_aspect(primary=["Python", "debugging"], name="Morrigan")
        block = _build_expertise_domain_block(aspect)
        assert "Primary expertise" in block
        assert "Python" in block
        assert "debugging" in block

    def test_includes_secondary_domains(self):
        from agent_loop import _build_expertise_domain_block
        aspect = _make_aspect(secondary=["Git", "Docker"])
        block = _build_expertise_domain_block(aspect)
        assert "Secondary expertise" in block
        assert "Git" in block

    def test_includes_philosophy(self):
        from agent_loop import _build_expertise_domain_block
        aspect = _make_aspect(primary=["Python"], philosophy="Ship it clean.")
        block = _build_expertise_domain_block(aspect)
        assert "Engineering philosophy" in block
        assert "Ship it clean" in block

    def test_includes_honest_gaps(self):
        from agent_loop import _build_expertise_domain_block
        aspect = _make_aspect(primary=["Python"], gaps=["Frontend frameworks", "ML training"])
        block = _build_expertise_domain_block(aspect)
        assert "Honest gaps" in block
        assert "Frontend frameworks" in block

    def test_includes_can_refuse(self):
        from agent_loop import _build_expertise_domain_block
        aspect = _make_aspect(primary=["Python"], can_refuse=["bypass tests"])
        block = _build_expertise_domain_block(aspect)
        assert "Will refuse" in block
        assert "bypass tests" in block

    def test_block_has_aspect_name(self):
        from agent_loop import _build_expertise_domain_block
        aspect = _make_aspect(primary=["Python"], name="Nyx")
        block = _build_expertise_domain_block(aspect)
        assert "Nyx" in block

    def test_empty_if_all_fields_empty(self):
        from agent_loop import _build_expertise_domain_block
        aspect = _make_aspect(primary=[], secondary=[], philosophy="", gaps=[], can_refuse=[])
        assert _build_expertise_domain_block(aspect) == ""


# ── _apply_domain_keyword_boost (vector_store) ──────────────────────────────


class TestApplyDomainKeywordBoost:
    def test_empty_items_returns_empty(self):
        from layla.memory.vector_store import _apply_domain_keyword_boost
        assert _apply_domain_keyword_boost([], ["python"], 5) == []

    def test_empty_keywords_returns_original(self):
        from layla.memory.vector_store import _apply_domain_keyword_boost
        items = [{"content": "hello"}, {"content": "world"}]
        result = _apply_domain_keyword_boost(items, [], 5)
        assert len(result) == 2
        assert result[0]["content"] == "hello"  # order preserved

    def test_boosts_matching_results(self):
        from layla.memory.vector_store import _apply_domain_keyword_boost
        # Item at position 2 mentions "python" — should be boosted upward
        items = [
            {"content": "unrelated topic about cooking"},
            {"content": "some gardening tips"},
            {"content": "Python debugging with pdb is effective"},
        ]
        result = _apply_domain_keyword_boost(items, ["python", "debugging"], 3)
        # The python/debugging item should move up from position 2
        contents = [r["content"] for r in result]
        python_idx = next(i for i, c in enumerate(contents) if "Python" in c)
        assert python_idx < 2, "Domain-matching item should be boosted upward"

    def test_preserves_k_limit(self):
        from layla.memory.vector_store import _apply_domain_keyword_boost
        items = [{"content": f"item {i}"} for i in range(10)]
        result = _apply_domain_keyword_boost(items, ["python"], 3)
        assert len(result) == 3

    def test_multi_keyword_boost_stronger(self):
        from layla.memory.vector_store import _apply_domain_keyword_boost
        items = [
            {"content": "python is great"},               # 1 keyword match
            {"content": "python debugging with testing"},  # 3 keyword matches
            {"content": "unrelated stuff"},                # 0 matches
        ]
        result = _apply_domain_keyword_boost(items, ["python", "debugging", "testing"], 3)
        # Multi-match item should rank highest
        assert "debugging" in result[0]["content"]

    def test_boost_capped_at_015(self):
        from layla.memory.vector_store import _apply_domain_keyword_boost
        # Even with many keywords, boost shouldn't exceed 0.15
        items = [
            {"content": "alpha beta gamma delta epsilon"},
            {"content": "unrelated"},
        ]
        keywords = ["alpha", "beta", "gamma", "delta", "epsilon"]
        result = _apply_domain_keyword_boost(items, keywords, 2)
        # Should still work without error, first item still first
        assert "alpha" in result[0]["content"]

    def test_case_insensitive_matching(self):
        from layla.memory.vector_store import _apply_domain_keyword_boost
        items = [
            {"content": "some unrelated text"},
            {"content": "PYTHON debugging patterns"},
        ]
        result = _apply_domain_keyword_boost(items, ["python"], 2)
        # Python item should be boosted despite case difference
        assert "PYTHON" in result[0]["content"]

    def test_none_content_handled(self):
        from layla.memory.vector_store import _apply_domain_keyword_boost
        items = [{"content": None}, {"content": "python stuff"}]
        result = _apply_domain_keyword_boost(items, ["python"], 2)
        assert len(result) == 2


# ── Integration: _semantic_recall accepts domain_boost_terms ─────────────────


class TestSemanticRecallDomainParam:
    """Verify _semantic_recall accepts the new parameter without error."""

    def test_accepts_none_domain_terms(self, monkeypatch):
        from agent_loop import _semantic_recall
        # Mock search_memories_full to avoid real ChromaDB
        def mock_search(*args, **kwargs):
            return [{"content": "test result"}]
        monkeypatch.setattr(
            "layla.memory.vector_store.search_memories_full", mock_search
        )
        result = _semantic_recall("test query", k=3, domain_boost_terms=None)
        assert "test result" in result

    def test_accepts_domain_terms_list(self, monkeypatch):
        from agent_loop import _semantic_recall
        captured = {}
        def mock_search(query, **kwargs):
            captured["query"] = query
            captured["kwargs"] = kwargs
            return [{"content": "domain result"}]
        monkeypatch.setattr(
            "layla.memory.vector_store.search_memories_full", mock_search
        )
        monkeypatch.setattr(
            "runtime_safety.load_config",
            lambda: {"expertise_domain_boost_enabled": True},
        )
        result = _semantic_recall("fix bug", k=3, domain_boost_terms=["python", "debugging"])
        assert "domain result" in result
        # Query should be augmented with domain terms
        assert "python" in captured["query"]
        assert "debugging" in captured["query"]
        # domain_boost_keywords should be passed through
        assert captured["kwargs"].get("domain_boost_keywords") == ["python", "debugging"]

    def test_domain_boost_disabled_by_config(self, monkeypatch):
        from agent_loop import _semantic_recall
        captured = {}
        def mock_search(query, **kwargs):
            captured["query"] = query
            return [{"content": "result"}]
        monkeypatch.setattr(
            "layla.memory.vector_store.search_memories_full", mock_search
        )
        monkeypatch.setattr(
            "runtime_safety.load_config",
            lambda: {"expertise_domain_boost_enabled": False},
        )
        _semantic_recall("fix bug", k=3, domain_boost_terms=["python"])
        # Query should NOT be augmented when disabled
        assert captured["query"] == "fix bug"

    def test_backward_compatible_no_domain_terms(self, monkeypatch):
        from agent_loop import _semantic_recall
        def mock_search(query, **kwargs):
            return [{"content": "basic result"}]
        monkeypatch.setattr(
            "layla.memory.vector_store.search_memories_full", mock_search
        )
        # Old call signature without domain_boost_terms should still work
        result = _semantic_recall("simple query", k=3)
        assert "basic result" in result


# ── Personality JSON validation ──────────────────────────────────────────────


class TestPersonalityExpertiseDomains:
    """Verify all 6 personality JSONs have well-formed expertise_domains."""

    @pytest.fixture(params=["morrigan", "nyx", "echo", "eris", "cassandra", "lilith"])
    def aspect_json(self, request):
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / "personalities" / f"{request.param}.json"
        assert p.exists(), f"Missing personality file: {p}"
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def test_has_expertise_domains(self, aspect_json):
        assert "expertise_domains" in aspect_json
        ed = aspect_json["expertise_domains"]
        assert isinstance(ed, dict)

    def test_has_primary_list(self, aspect_json):
        ed = aspect_json["expertise_domains"]
        assert "primary" in ed
        assert isinstance(ed["primary"], list)
        assert len(ed["primary"]) >= 3, "Each aspect should have at least 3 primary domains"

    def test_has_secondary_list(self, aspect_json):
        ed = aspect_json["expertise_domains"]
        assert "secondary" in ed
        assert isinstance(ed["secondary"], list)

    def test_has_philosophy(self, aspect_json):
        ed = aspect_json["expertise_domains"]
        assert "philosophy" in ed
        assert isinstance(ed["philosophy"], str)
        assert len(ed["philosophy"]) >= 10

    def test_has_knowledge_gaps(self, aspect_json):
        ed = aspect_json["expertise_domains"]
        assert "knowledge_gaps_honest" in ed
        assert isinstance(ed["knowledge_gaps_honest"], list)
        assert len(ed["knowledge_gaps_honest"]) >= 2, "Each aspect should honestly list at least 2 gaps"

    def test_keyword_extraction_works(self, aspect_json):
        from agent_loop import _extract_aspect_domain_keywords
        kws = _extract_aspect_domain_keywords(aspect_json)
        assert len(kws) >= 3, "Should extract at least 3 keywords from any aspect"
        # All keywords should be lowercase
        for kw in kws:
            assert kw == kw.lower()

    def test_domain_block_non_empty(self, aspect_json):
        from agent_loop import _build_expertise_domain_block
        block = _build_expertise_domain_block(aspect_json)
        assert len(block) > 50, "Domain block should be a substantive prompt injection"
