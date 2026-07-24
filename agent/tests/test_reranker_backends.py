"""BL-103: reranker backend chain (flashrank → cross-encoder → bm25), caching, selection.

These assertions were written against the unwired `services/retrieval/reranker.py`, which was
the only thing keeping that module alive. The module is gone; the capability it uniquely had —
the FlashRank backend and the config-driven backend order — was folded into the LIVE reranker
at `layla/memory/vector_store_rerank.py`, so the tests now point there.

Contract difference to keep in mind: the live reranker takes and returns the CALLER'S doc
dicts (reordered), not `{content, score, original_index}` records. Ranking assertions are
therefore made on identity/content rather than on an index field.

Degradation paths (cross-encoder missing / scoring raising) are covered separately and more
strictly in test_vector_store_rerank_backstop.py.
"""
from __future__ import annotations

import sys
import types

import pytest

from layla.memory import vector_store_rerank as vsr


@pytest.fixture(autouse=True)
def _fresh():
    vsr.reset_reranker_cache()
    yield
    vsr.reset_reranker_cache()


@pytest.fixture
def _no_ce(monkeypatch):
    """Neutralise both cross-encoders so a test targets the flashrank/bm25 links only."""
    monkeypatch.setattr(vsr, "_get_bge_cross_encoder", lambda *a, **kw: None)
    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: None)


def test_backend_order_selection():
    assert vsr._backend_order("auto") == ["flashrank", "cross_encoder", "bm25"]
    assert vsr._backend_order("flashrank") == ["flashrank", "bm25"]
    assert vsr._backend_order("cross_encoder") == ["cross_encoder", "bm25"]
    assert vsr._backend_order("bm25") == ["bm25"]
    assert vsr._backend_order("") == ["flashrank", "cross_encoder", "bm25"]
    assert vsr._backend_order(None) == ["flashrank", "cross_encoder", "bm25"]


def test_bm25_ranks_relevant_doc_first():
    docs = [
        {"content": "A recipe for chocolate cake with butter and sugar."},
        {"content": "FastAPI async endpoints use await and async def for concurrency."},
        {"content": "The weather today is sunny with a light breeze."},
    ]
    out = vsr._bm25_rerank("fastapi async await concurrency", docs, 3)
    assert out[0] is docs[1]  # the FastAPI doc wins


def test_bm25_top_k_limits_output():
    docs = [{"content": f"document {i}"} for i in range(10)]
    assert len(vsr._bm25_rerank("document", docs, 3)) == 3


def test_bm25_orders_by_descending_relevance():
    docs = [
        {"content": "the the the"},
        {"content": "python web python web"},
        {"content": "python async patterns"},
    ]
    out = vsr._bm25_rerank("python web", docs, 3)
    # Two query terms twice each beats one term once, which beats no terms at all.
    assert out[0] is docs[1]
    assert out[1] is docs[2]
    assert out[2] is docs[0]


def test_auto_falls_back_to_bm25_when_no_ml(_no_ce, monkeypatch):
    """flashrank + sentence_transformers absent → auto must reach bm25 and still rank."""
    monkeypatch.setitem(sys.modules, "flashrank", None)  # force ImportError
    vsr.reset_reranker_cache()
    docs = [
        {"content": "unrelated text about gardening soil"},
        {"content": "async def foo() awaits the coroutine"},
    ]
    out = vsr.rerank("async patterns coroutine", docs, k=2)
    assert out[0] is docs[1]
    assert vsr._flashrank_failed is True


def test_bm25_only_backend_skips_the_model_backends(monkeypatch):
    """reranker_backend="bm25" is a configured choice, so no model must even be probed."""
    probes: list[str] = []
    monkeypatch.setattr(vsr, "_get_flashrank", lambda: probes.append("flashrank"))
    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: probes.append("ce"))
    monkeypatch.setattr(vsr, "_get_bge_cross_encoder", lambda *a, **kw: None)
    monkeypatch.setattr(
        vsr, "_backend_order", lambda pref: ["bm25"]
    )
    docs = [{"content": "gardening soil"}, {"content": "quantum qubits entanglement"}]
    out = vsr.rerank("quantum qubits", docs, k=1)
    assert probes == [], f"bm25-only config still probed a model backend: {probes}"
    assert out[0] is docs[1]


def _fake_flashrank(builds: dict) -> types.ModuleType:
    class _FakeRanker:
        def __init__(self, *a, **k):
            builds["n"] += 1

        def rerank(self, req):
            # return passages in reverse order with descending scores
            ps = list(req.passages)
            return [
                {"id": p["id"], "text": p["text"], "score": 1.0 - i * 0.1}
                for i, p in enumerate(reversed(ps))
            ]

    class _FakeReq:
        def __init__(self, query, passages):
            self.query = query
            self.passages = passages

    fake = types.ModuleType("flashrank")
    fake.Ranker = _FakeRanker
    fake.RerankRequest = _FakeReq
    return fake


def test_flashrank_used_and_cached(monkeypatch):
    """Inject a fake flashrank and assert the Ranker is built ONCE across two calls."""
    builds = {"n": 0}
    monkeypatch.setitem(sys.modules, "flashrank", _fake_flashrank(builds))
    vsr.reset_reranker_cache()

    docs = [{"content": "doc zero"}, {"content": "doc one"}, {"content": "doc two"}]
    out1 = vsr.rerank("q", docs, k=3)
    out2 = vsr.rerank("q", docs, k=3)
    assert builds["n"] == 1, "model rebuilt per call — the cache is not holding"
    assert out1[0] is docs[2], "reversed → last doc first; flashrank did not win the chain"
    assert out2 == out1


def test_flashrank_returns_caller_dicts_not_copies(monkeypatch):
    """The live contract: metadata (ids, source) must survive the rerank."""
    builds = {"n": 0}
    monkeypatch.setitem(sys.modules, "flashrank", _fake_flashrank(builds))
    vsr.reset_reranker_cache()

    docs = [{"content": "a", "id": "a", "meta": {"src": "x"}}, {"content": "b", "id": "b"}]
    out = vsr.rerank("q", docs, k=1)
    assert out[0] is docs[1]


def test_flashrank_scoring_failure_falls_through_to_next_backend(_no_ce, monkeypatch):
    """A flashrank blow-up must not abort the chain — bm25 still has to produce a ranking."""

    class _ExplodingRanker:
        def rerank(self, req):
            raise RuntimeError("simulated onnx failure")

    monkeypatch.setitem(sys.modules, "flashrank", _fake_flashrank({"n": 0}))
    monkeypatch.setattr(vsr, "_get_flashrank", lambda: _ExplodingRanker())

    docs = [
        {"content": "gardening trowels and potting soil"},
        {"content": "quantum entanglement of superconducting qubits"},
    ]
    out = vsr.rerank("quantum entanglement qubits", docs, k=1)
    assert out[0] is docs[1], "chain stopped at the failed backend instead of reaching bm25"


def test_empty_docs_passthrough():
    assert vsr.rerank("q", []) == []


def test_reset_reranker_cache_clears_every_memo():
    vsr._cross_encoder = object()
    vsr._cross_encoder_failed = True
    vsr._bge_cross_encoder = object()
    vsr._bge_cross_encoder_model = "some-model"
    vsr._bge_cross_encoder_failed = True
    vsr._flashrank_ranker = object()
    vsr._flashrank_failed = True

    vsr.reset_reranker_cache()

    assert vsr._cross_encoder is None
    assert vsr._cross_encoder_failed is False
    assert vsr._bge_cross_encoder is None
    assert vsr._bge_cross_encoder_model is None
    assert vsr._bge_cross_encoder_failed is False
    assert vsr._flashrank_ranker is None
    assert vsr._flashrank_failed is False
