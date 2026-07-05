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
