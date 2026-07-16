"""BL-378: the LIVE reranker's BM25 backstop (layla/memory/vector_store_rerank.py).

`rerank()` had TWO silent degradation paths, both `return docs[:k]`:

  PATH A  `_get_cross_encoder()` returns None — sentence-transformers is not installed, OR the
          model was never cached and the machine is offline (BL-374: there is no
          local_files_only anywhere in the repo, so an offline first run lands here).
  PATH B  the model loaded but `.predict()` raised.

Both returned the retriever's arbitrary first k docs, UNRANKED, with no error and nothing a
caller or user could observe — indistinguishable from a successful rerank. Path B logged
nothing whatsoever.

Each path is tested SEPARATELY below, and each test is written to FAIL if its own guard is
reverted to `return docs[:k]`. That is the point: a single test that exercises one path while
claiming to cover both is how a guard ends up guarding nothing.

The discriminator: the BM25-correct answer is the LAST doc, so `docs[:k]` returns the gardening
doc and BM25 returns the quantum doc. Passing by accident is not available.
"""
from __future__ import annotations

import logging

import pytest

from layla.memory import vector_store_rerank as vsr

QUERY = "quantum entanglement superconducting qubits"

# Deliberately ordered so the relevant doc is LAST: docs[:1] -> gardening, BM25 -> quantum.
DOCS = [
    {"content": "A guide to gardening tools, trowels, pruning shears and potting soil."},
    {"content": "Sunny weather today with a light breeze and scattered afternoon clouds."},
    {"content": "Quantum entanglement between superconducting qubits enables two-qubit gates."},
]
RELEVANT = DOCS[2]["content"]


@pytest.fixture(autouse=True)
def _reset_module_cache():
    """rerank() memoises the cross-encoder + its failure at module level; isolate each test."""
    vsr._cross_encoder = None
    vsr._cross_encoder_failed = False
    yield
    vsr._cross_encoder = None
    vsr._cross_encoder_failed = False


class _ExplodingCrossEncoder:
    """Loads fine, then fails at scoring time — exercises PATH B specifically."""

    def predict(self, pairs, **kwargs):
        raise RuntimeError("simulated CUDA OOM during scoring")


def _no_bge(monkeypatch):
    """Neutralise the optional BGE branch so tests target the default cross-encoder path."""
    monkeypatch.setattr(vsr, "_get_bge_cross_encoder", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# PATH A — cross-encoder unavailable (the offline / not-installed case)
# ---------------------------------------------------------------------------

def test_path_a_model_unavailable_falls_back_to_bm25(monkeypatch):
    """Reverting path A to `return docs[:k]` makes this fail: it would yield the gardening doc."""
    _no_bge(monkeypatch)
    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: None)

    out = vsr.rerank(QUERY, DOCS, k=1)

    assert len(out) == 1
    assert out[0]["content"] == RELEVANT, (
        "PATH A returned the retriever's first doc unranked — the BM25 backstop did not run"
    )


def test_path_a_warns_when_degrading(monkeypatch, caplog):
    """Removing path A's logger.warning makes this fail — the degradation must be observable."""
    _no_bge(monkeypatch)
    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: None)

    with caplog.at_level(logging.WARNING, logger="layla"):
        vsr.rerank(QUERY, DOCS, k=1)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "PATH A degraded silently: no WARNING was emitted"
    assert any("BM25" in r.getMessage() for r in warnings)
    assert any("cross-encoder unavailable" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# PATH B — cross-encoder present but scoring raises
# ---------------------------------------------------------------------------

def test_path_b_scoring_failure_falls_back_to_bm25(monkeypatch):
    """Reverting path B to `return docs[:k]` makes this fail: it would yield the gardening doc.

    Distinct from path A: _get_cross_encoder() succeeds here, so path A is never reached.
    """
    _no_bge(monkeypatch)
    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: _ExplodingCrossEncoder())

    out = vsr.rerank(QUERY, DOCS, k=1)

    assert len(out) == 1
    assert out[0]["content"] == RELEVANT, (
        "PATH B swallowed the scoring error and returned docs[:k] unranked"
    )


def test_path_b_warns_when_degrading(monkeypatch, caplog):
    """Removing path B's logger.warning makes this fail. This except logged NOTHING before."""
    _no_bge(monkeypatch)
    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: _ExplodingCrossEncoder())

    with caplog.at_level(logging.WARNING, logger="layla"):
        vsr.rerank(QUERY, DOCS, k=1)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "PATH B degraded silently: no WARNING was emitted"
    assert any("scoring failed" in r.getMessage() for r in warnings)
    assert any("simulated CUDA OOM" in r.getMessage() for r in warnings), (
        "the underlying cause must reach the log, not just the fact of failure"
    )


def test_path_a_and_path_b_are_distinct_code_paths(monkeypatch):
    """Guards the tests above from collapsing into one path.

    If someone deletes the `if ce is None` branch, path A's inputs would fall through into the
    try/except and be 'covered' by path B's guard — the two tests would both pass while one
    guard is gone. Here we assert the branch is actually taken: a cross-encoder that would
    score CORRECTLY if reached still yields the BM25 result when _get_cross_encoder returns
    None, proving path A returns before any scoring happens.
    """
    _no_bge(monkeypatch)
    calls: list[int] = []

    class _CountingCrossEncoder:
        def predict(self, pairs, **kwargs):
            calls.append(1)
            return [1.0, 0.0, 0.0]  # would rank the GARDENING doc first

    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: None)
    out = vsr.rerank(QUERY, DOCS, k=1)
    assert calls == [], "path A must return before scoring is attempted"
    assert out[0]["content"] == RELEVANT

    # Same inputs, but the encoder is reachable -> its (wrong) ranking must win, proving the
    # scoring path is live and that path A's result above really came from the None branch.
    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: _CountingCrossEncoder())
    out2 = vsr.rerank(QUERY, DOCS, k=1)
    assert calls == [1]
    assert out2[0]["content"] == DOCS[0]["content"]


# ---------------------------------------------------------------------------
# BM25 unit behaviour
# ---------------------------------------------------------------------------

def test_bm25_preserves_retriever_order_when_query_has_no_tokens():
    """An empty query is not a degradation — there is nothing to rank on, so the retriever's
    order stands. This must NOT warn or reorder."""
    assert vsr._bm25_rerank("", DOCS, 2) == DOCS[:2]
    assert vsr._bm25_rerank("!!! ???", DOCS, 2) == DOCS[:2]


def test_bm25_handles_docs_with_no_text():
    empty = [{"content": ""}, {"content": ""}]
    assert vsr._bm25_rerank(QUERY, empty, 2) == empty[:2]


def test_bm25_reads_the_text_key_as_well_as_content():
    docs = [
        {"text": "gardening trowels and potting soil"},
        {"text": "quantum entanglement of superconducting qubits"},
    ]
    out = vsr._bm25_rerank(QUERY, docs, 1)
    assert out[0]["text"].startswith("quantum")


def test_bm25_respects_k():
    assert len(vsr._bm25_rerank(QUERY, DOCS, 2)) == 2
    assert len(vsr._bm25_rerank(QUERY, DOCS, 99)) == len(DOCS)


def test_rerank_returns_original_dict_objects_not_copies(monkeypatch):
    """Callers rely on doc metadata (ids, scores, source) surviving the rerank."""
    _no_bge(monkeypatch)
    monkeypatch.setattr(vsr, "_get_cross_encoder", lambda: None)
    docs = [
        {"content": "gardening soil", "id": "a", "meta": {"src": "x"}},
        {"content": "quantum entanglement superconducting qubits", "id": "b", "meta": {"src": "y"}},
    ]
    out = vsr.rerank(QUERY, docs, k=1)
    assert out[0] is docs[1], "rerank must return the caller's own dict objects"
