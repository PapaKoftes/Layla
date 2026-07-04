"""BL-103: reranker backend chain (flashrank → cross-encoder → bm25), caching, selection."""
from __future__ import annotations

import sys
import types

import pytest

from services.retrieval import reranker as rr


@pytest.fixture(autouse=True)
def _fresh():
    rr.reset_reranker_cache()
    yield
    rr.reset_reranker_cache()


def test_backend_order_selection():
    assert rr._backend_order("auto") == ["flashrank", "cross_encoder", "bm25"]
    assert rr._backend_order("flashrank") == ["flashrank", "bm25"]
    assert rr._backend_order("cross_encoder") == ["cross_encoder", "bm25"]
    assert rr._backend_order("bm25") == ["bm25"]
    assert rr._backend_order("") == ["flashrank", "cross_encoder", "bm25"]


def test_bm25_ranks_relevant_doc_first():
    docs = [
        "A recipe for chocolate cake with butter and sugar.",
        "FastAPI async endpoints use await and async def for concurrency.",
        "The weather today is sunny with a light breeze.",
    ]
    out = rr.rerank("fastapi async await concurrency", docs, top_k=3, backend="bm25")
    assert out[0]["original_index"] == 1          # the FastAPI doc wins
    assert out[0]["score"] > out[-1]["score"]


def test_empty_and_blank_query():
    assert rr.rerank("q", [], top_k=3) == []
    passthrough = rr.rerank("   ", ["a", "b"], top_k=2)
    assert [p["original_index"] for p in passthrough] == [0, 1]


def test_auto_falls_back_to_bm25_when_no_ml(monkeypatch):
    # flashrank + sentence_transformers are absent in the test venv → auto must reach bm25.
    monkeypatch.setitem(sys.modules, "flashrank", None)          # force ImportError
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    rr.reset_reranker_cache()
    out = rr.rerank("async patterns", ["async def foo()", "unrelated text"], top_k=2, cfg={"reranker_backend": "auto"})
    assert out and out[0]["original_index"] == 0
    assert "flashrank" in rr._unavailable and "cross_encoder" in rr._unavailable


def test_flashrank_used_and_cached(monkeypatch):
    # Inject a fake flashrank module and assert the Ranker is built ONCE across two calls.
    builds = {"n": 0}

    class _FakeRanker:
        def __init__(self, *a, **k):
            builds["n"] += 1

        def rerank(self, req):
            # return passages in reverse order with descending scores
            ps = list(req.passages)
            return [{"id": p["id"], "text": p["text"], "score": 1.0 - i * 0.1} for i, p in enumerate(reversed(ps))]

    class _FakeReq:
        def __init__(self, query, passages):
            self.query = query
            self.passages = passages

    fake = types.ModuleType("flashrank")
    fake.Ranker = _FakeRanker
    fake.RerankRequest = _FakeReq
    monkeypatch.setitem(sys.modules, "flashrank", fake)
    rr.reset_reranker_cache()

    docs = ["doc zero", "doc one", "doc two"]
    out1 = rr.rerank("q", docs, top_k=3, backend="flashrank")
    out2 = rr.rerank("q", docs, top_k=3, backend="flashrank")
    assert builds["n"] == 1                          # cached — model built once, not per call
    assert out1[0]["original_index"] == 2            # reversed → last doc first
    assert out2 == out1
