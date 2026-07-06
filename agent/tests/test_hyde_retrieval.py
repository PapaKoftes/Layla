"""HyDE retrieval (search_with_hyde) was shipped but untested. Verify it uses the
hypothetical-document path (generate → embed → fuse) and falls back to dense search when
the LLM is unavailable."""
from __future__ import annotations

import layla.memory.vector_store as vs


def test_hyde_uses_hypothetical_and_fuses(monkeypatch):
    monkeypatch.setattr(
        "services.llm.llm_gateway.run_completion",
        lambda *a, **k: {"choices": [{"message": {"content": "A sufficiently long hypothetical factual answer about the topic."}}]},
        raising=False,
    )
    monkeypatch.setattr(vs, "embed", lambda t: [0.1] * 8, raising=False)
    calls = {"n": 0}

    def _search(vec, k=5):
        calls["n"] += 1
        return [{"content": f"doc{calls['n']}", "id": calls["n"], "score": 0.9}]

    monkeypatch.setattr(vs, "search_similar", _search, raising=False)
    monkeypatch.setattr(vs, "_reciprocal_rank_fusion", lambda lists, k: lists[0][:k], raising=False)

    res = vs.search_with_hyde("what is X?", k=3)
    assert res                      # got results via the HyDE path
    assert calls["n"] >= 2          # searched with BOTH the hypothetical vector and the original query (fusion)


def test_hyde_falls_back_when_llm_unavailable(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("no llm")

    monkeypatch.setattr("services.llm.llm_gateway.run_completion", _boom, raising=False)
    monkeypatch.setattr(vs, "embed", lambda t: [0.1] * 8, raising=False)
    monkeypatch.setattr(vs, "search_similar", lambda vec, k=5: [{"content": "fallback", "id": 1}], raising=False)

    assert vs.search_with_hyde("q", k=3, fallback=True) == [{"content": "fallback", "id": 1}]
    assert vs.search_with_hyde("q", k=3, fallback=False) == []
