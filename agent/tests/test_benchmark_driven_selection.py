"""BL-174 / REQ-85: benchmark-driven model selection among compatible candidates."""
from __future__ import annotations

import pytest

from install import model_selector as ms

_CATALOG = [
    {"name": "small", "filename": "small.gguf", "ram_required": 4, "url": "http://x/small.gguf", "family": "x"},
    {"name": "medium", "filename": "medium.gguf", "ram_required": 8, "url": "http://x/medium.gguf", "family": "x"},
    {"name": "large", "filename": "large.gguf", "ram_required": 12, "url": "http://x/large.gguf", "family": "x"},
]
_HW = {"ram_gb": 32, "vram_gb": 0}


@pytest.fixture(autouse=True)
def _catalog(monkeypatch):
    monkeypatch.setattr(ms, "load_catalog", lambda: [dict(m) for m in _CATALOG])


def test_no_benchmarks_is_fits_first(monkeypatch):
    monkeypatch.setattr("services.llm.model_benchmark.get_all_benchmarks", lambda: {})
    assert ms.recommend_model(_HW)["name"] == "small"   # smallest-first heuristic unchanged


def test_benchmark_prefers_best_measured(monkeypatch):
    monkeypatch.setattr("services.llm.model_benchmark.get_all_benchmarks", lambda: {
        "small.gguf": {"pass_at_1": 0.4, "tok_per_s": 12},
        "medium.gguf": {"pass_at_1": 0.9, "tok_per_s": 6},
    })
    assert ms.recommend_model(_HW)["name"] == "medium"   # best pass@1 wins


def test_benchmark_tiebreak_on_speed(monkeypatch):
    monkeypatch.setattr("services.llm.model_benchmark.get_all_benchmarks", lambda: {
        "small.gguf": {"pass_at_1": 0.8, "tok_per_s": 20},
        "medium.gguf": {"pass_at_1": 0.8, "tok_per_s": 6},
    })
    assert ms.recommend_model(_HW)["name"] == "small"   # equal quality → faster wins


def test_benchmark_only_ranks_compatible(monkeypatch):
    monkeypatch.setattr("services.llm.model_benchmark.get_all_benchmarks", lambda: {
        "large.gguf": {"pass_at_1": 0.99, "tok_per_s": 30},   # best but won't fit
        "small.gguf": {"pass_at_1": 0.5, "tok_per_s": 10},
    })
    assert ms.recommend_model({"ram_gb": 6, "vram_gb": 0})["name"] == "small"


def test_benchmark_uses_real_producer_key(monkeypatch):
    """The store shape run_benchmark ACTUALLY writes (model_benchmark.py:115): speed under
    `tokens_per_sec`, and NO pass_at_1. The scorer used to read `tok_per_s` — a key nothing
    writes — so every measured model scored (0.0, 0.0), tied, and fits-first always won: REQ-85
    was silently inert in production even after on-box measurement. With the real key read, the
    faster measured model among fits is chosen. Teeth: revert model_selector _score to `tok_per_s`
    and this fails (both score (0,0) → the fits-first 'small' is returned instead of 'medium')."""
    monkeypatch.setattr("services.llm.model_benchmark.get_all_benchmarks", lambda: {
        "small.gguf": {"tokens_per_sec": 8, "first_token_ms": 500, "memory_mb": 900},
        "medium.gguf": {"tokens_per_sec": 20, "first_token_ms": 300, "memory_mb": 1800},
    })
    assert ms.recommend_model(_HW)["name"] == "medium"   # faster MEASURED model wins on real keys
