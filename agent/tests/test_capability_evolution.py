"""Tests for capability evolution system (benchmark + registry — the wired half).

The capability_discovery module (PyPI/GitHub candidate scanning) was removed as
dead code: nothing consumed discovered candidates (no discover→benchmark→swap
loop was ever built). The benchmark_suite + capabilities.registry below are the
live, wired pieces and stay covered.
"""

from capabilities.registry import get_active_implementation, list_implementations
from services.infrastructure.benchmark_suite import run_benchmark


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
