"""Tests for capability evolution system."""

from capabilities.registry import get_active_implementation, list_implementations
from services.benchmark_suite import run_benchmark
from services.capability_discovery import (
    CAPABILITY_SEARCH_TERMS,
    discover_candidate_libraries,
    fetch_github_candidates,
    fetch_pypi_candidates,
)


def test_discover_candidate_libraries():
    candidates = discover_candidate_libraries("vector_search", use_cache=False)
    assert isinstance(candidates, list)
    assert len(candidates) >= 1


def test_fetch_pypi_candidates():
    candidates = fetch_pypi_candidates("vector_search")
    assert isinstance(candidates, list)
    names = [c.name for c in candidates]
    assert "chromadb" in names or "faiss-cpu" in names


def test_fetch_github_candidates():
    candidates = fetch_github_candidates("embedding")
    assert isinstance(candidates, list)


def test_capability_search_terms():
    assert "vector_search" in CAPABILITY_SEARCH_TERMS
    assert "embedding" in CAPABILITY_SEARCH_TERMS
    assert "reranker" in CAPABILITY_SEARCH_TERMS
    assert "web_scraper" in CAPABILITY_SEARCH_TERMS


def test_run_benchmark_unknown_capability():
    result = run_benchmark("unknown_cap", "impl", "pkg")
    assert result.get("ok") is False
    assert "error" in result


def test_get_active_implementation_uses_config():
    impl = get_active_implementation("vector_search", cfg={"capability_impls": {"vector_search": "chromadb"}})
    assert impl is not None
    assert impl.id == "chromadb"


def test_get_active_implementation_fallback():
    impl = get_active_implementation("vector_search")
    assert impl is not None


def test_list_implementations():
    impls = list_implementations("embedding")
    assert len(impls) >= 1
    assert any(i.id == "sentence_transformers" for i in impls)
