"""Tests for layla.codex — the personal knowledge codex module."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ensure_db():
    """Run migrations so entity/relationship tables exist in the test DB."""
    from layla.memory.migrations import migrate
    migrate()


# ── codex_db tests ───────────────────────────────────────────────────────────

class TestUpsertAndGet:
    def test_upsert_creates_entity(self):
        from layla.codex.codex_db import upsert_entity, get_entity

        result = upsert_entity(
            "technology", "Python",
            description="A programming language",
            confidence=0.9,
            source="test",
        )
        assert result, "upsert_entity should return a non-empty dict"
        assert result["canonical_name"] == "python"
        assert result["type"] == "technology"

        # Retrieve by ID
        fetched = get_entity(result["id"])
        assert fetched is not None
        assert fetched["canonical_name"] == "python"
        assert fetched["description"] == "A programming language"

    def test_upsert_merges_on_duplicate(self):
        from layla.codex.codex_db import upsert_entity, get_entity

        r1 = upsert_entity(
            "concept", "Machine Learning",
            description="Subset of AI",
            tags=["ai"],
            confidence=0.6,
        )
        r2 = upsert_entity(
            "concept", "Machine Learning",
            description="Statistical learning from data",
            tags=["statistics"],
            confidence=0.8,
        )
        assert r1["id"] == r2["id"], "Same type+name should produce same ID"

        fetched = get_entity(r1["id"])
        assert fetched is not None
        # Higher confidence description wins
        assert fetched["description"] == "Statistical learning from data"
        # Tags are unioned
        tags = fetched["tags"]
        assert "ai" in tags
        assert "statistics" in tags

    def test_get_nonexistent_returns_none(self):
        from layla.codex.codex_db import get_entity

        assert get_entity("ent_does_not_exist_123") is None


class TestSearch:
    def test_search_finds_by_name(self):
        from layla.codex.codex_db import upsert_entity, search_entities

        upsert_entity("technology", "FastAPI", description="Web framework", confidence=0.8)

        results = search_entities("fastapi")
        assert len(results) >= 1
        names = [r["canonical_name"] for r in results]
        assert "fastapi" in names

    def test_search_filters_by_type(self):
        from layla.codex.codex_db import upsert_entity, search_entities

        upsert_entity("person", "Alice Smith", confidence=0.7)
        upsert_entity("technology", "AliceDB", confidence=0.7)

        results_person = search_entities("alice", entity_type="person")
        types = {r["type"] for r in results_person}
        assert types == {"person"} or len(results_person) == 0 or all(r["type"] == "person" for r in results_person)

    def test_search_respects_min_confidence(self):
        from layla.codex.codex_db import upsert_entity, search_entities

        upsert_entity("concept", "Low Confidence Concept", confidence=0.1)

        results = search_entities("low confidence concept", min_confidence=0.5)
        names = [r["canonical_name"] for r in results]
        assert "low confidence concept" not in names


class TestRelationships:
    def test_link_entities_creates_relationship(self):
        from layla.codex.codex_db import upsert_entity, link_entities, get_entity_relationships

        e1 = upsert_entity("person", "Bob", confidence=0.8)
        e2 = upsert_entity("project", "Layla", confidence=0.9)

        rel = link_entities(
            e1["id"], e2["id"], "worked_on",
            weight=0.8,
            evidence="Bob built Layla",
        )
        assert rel, "link_entities should return a non-empty dict"
        assert rel["type"] == "worked_on"
        assert rel["from_entity"] == e1["id"]
        assert rel["to_entity"] == e2["id"]

        # Check retrieval
        rels = get_entity_relationships(e1["id"])
        assert len(rels) >= 1
        rel_types = [r["type"] for r in rels]
        assert "worked_on" in rel_types


class TestGraph:
    def test_get_entity_graph_returns_nodes_and_edges(self):
        from layla.codex.codex_db import upsert_entity, link_entities, get_entity_graph

        e1 = upsert_entity("person", "Carol", confidence=0.8)
        e2 = upsert_entity("technology", "Rust", confidence=0.9)
        e3 = upsert_entity("project", "Servo", confidence=0.8)

        link_entities(e1["id"], e2["id"], "uses")
        link_entities(e2["id"], e3["id"], "is_part_of")

        graph = get_entity_graph(e1["id"], depth=2)
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) >= 2  # At least Carol and Rust
        assert len(graph["edges"]) >= 1

        node_ids = {n["id"] for n in graph["nodes"]}
        assert e1["id"] in node_ids
        assert e2["id"] in node_ids

    def test_graph_depth_1_limits_expansion(self):
        from layla.codex.codex_db import upsert_entity, link_entities, get_entity_graph

        a = upsert_entity("concept", "Alpha", confidence=0.8)
        b = upsert_entity("concept", "Beta", confidence=0.8)
        c = upsert_entity("concept", "Gamma", confidence=0.8)

        link_entities(a["id"], b["id"], "relates_to")
        link_entities(b["id"], c["id"], "relates_to")

        graph = get_entity_graph(a["id"], depth=1)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert a["id"] in node_ids
        assert b["id"] in node_ids
        # Gamma should NOT be in depth=1 from Alpha (it's 2 hops away)
        # (b is discovered at depth 1, but its neighbours aren't expanded)
        # Actually Alpha->Beta is 1 hop, Beta->Gamma is 2nd hop.
        # depth=1 means we only expand the initial frontier once.
        # So we get Alpha + Beta, but Beta's neighbours aren't expanded.
        assert c["id"] not in node_ids


class TestAggregates:
    def test_count_entities(self):
        from layla.codex.codex_db import upsert_entity, count_entities

        upsert_entity("skill", "Welding", confidence=0.8)
        upsert_entity("skill", "Soldering", confidence=0.8)

        total = count_entities()
        assert total >= 2

        skill_count = count_entities("skill")
        assert skill_count >= 2

    def test_list_entity_types(self):
        from layla.codex.codex_db import upsert_entity, list_entity_types

        upsert_entity("event", "Conference 2025", confidence=0.7)

        types = list_entity_types()
        assert "event" in types


# ── enricher tests ───────────────────────────────────────────────────────────

class TestEnricher:
    def test_regex_detects_programming_terms(self):
        from layla.codex.enricher import extract_entities

        text = "I learned Python and FastAPI today, also played with Docker containers."
        entities = extract_entities(text)
        names_lower = {e["name"].lower() for e in entities}
        assert "python" in names_lower
        assert "fastapi" in names_lower
        assert "docker" in names_lower

    def test_regex_detects_at_mentions(self):
        from layla.codex.enricher import extract_entities

        text = "Thanks @alice_dev for the review on the PR."
        entities = extract_entities(text)
        names = {e["name"] for e in entities}
        assert "@alice_dev" in names

    def test_regex_detects_camel_case(self):
        from layla.codex.enricher import extract_entities

        text = "The DataLoader class handles batch processing."
        entities = extract_entities(text)
        names = {e["name"] for e in entities}
        assert "DataLoader" in names

    def test_empty_text_returns_empty(self):
        from layla.codex.enricher import extract_entities

        assert extract_entities("") == []
        assert extract_entities("   ") == []


# ── linker tests ─────────────────────────────────────────────────────────────

class TestAutoLinker:
    def test_auto_link_learning_extracts_and_links(self):
        from layla.codex.codex_db import upsert_entity
        from layla.codex.linker import auto_link_learning

        # Pre-populate codex with a known entity
        upsert_entity("technology", "Django", description="Web framework", confidence=0.9)

        content = "Today I learned how to use Django REST framework with Redis for caching."
        links = auto_link_learning(content, learning_id=42)

        # Should have found at least Django and Redis
        linked_names = {l["entity_name"].lower() for l in links}
        assert "django" in linked_names or "redis" in linked_names
        assert len(links) >= 1

    def test_auto_link_empty_content(self):
        from layla.codex.linker import auto_link_learning

        assert auto_link_learning("", learning_id=1) == []
        assert auto_link_learning("   ", learning_id=2) == []

    def test_find_best_codex_match_exact(self):
        from layla.codex.codex_db import upsert_entity
        from layla.codex.linker import find_best_codex_match

        upsert_entity("technology", "PostgreSQL", confidence=0.9)

        match = find_best_codex_match("postgresql")
        assert match is not None
        assert match["canonical_name"] == "postgresql"

    def test_find_best_codex_match_no_match(self):
        from layla.codex.linker import find_best_codex_match

        match = find_best_codex_match("xyzzy_nonexistent_thing_12345")
        assert match is None
