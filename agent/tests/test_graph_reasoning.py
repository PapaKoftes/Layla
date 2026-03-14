"""Tests for graph_reasoning (entity extraction, graph expansion)."""

from services.graph_reasoning import expand_query_via_graph, extract_entities, get_expanded_context


def test_extract_entities_empty():
    assert extract_entities("") == []
    assert extract_entities(None) == []  # type: ignore


def test_extract_entities_without_spacy():
    # Without spaCy, returns [] (graceful fallback)
    result = extract_entities("John Smith works at Acme Corp.")
    assert isinstance(result, list)


def test_expand_query_empty_graph():
    # With empty graph, returns [] or uses fallback
    result = expand_query_via_graph("test query", max_hops=1, max_nodes=5)
    assert isinstance(result, list)


def test_get_expanded_context_empty():
    assert get_expanded_context("") == ""
    assert get_expanded_context("   ") == ""
    result = get_expanded_context("nonexistent query")
    assert isinstance(result, str)
