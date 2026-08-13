"""The knowledge-RAG hot path must never hang the turn on a COLD embedder download.

Regression for the CI hang (test_completion.py::test_workspace_context_appears_in_head timing out at
600s): a substantive goal triggers the knowledge-RAG path, whose first touch downloads the embedder
from HuggingFace. On a slow/cold network that download blocked the turn. The fix time-boxes the cold
path and degrades to the static reference docs, letting the download finish in the background.

Hermetic: no network, no chromadb — everything network-touching is monkeypatched.
"""
import time

import runtime_safety
from layla.memory import vector_store as vs
from services.prompts.system_head_builder import _resolve_knowledge_block


def test_run_with_time_budget_fast_slow_and_raising():
    # fast fn returns its value
    done, r = vs.run_with_time_budget(lambda: 42, 5.0)
    assert done is True and r == 42
    # slow fn is abandoned at the budget (worker keeps running as a daemon)
    t = time.time()
    done, r = vs.run_with_time_budget(lambda: (time.sleep(10) or "late"), 0.5)
    assert done is False and r is None
    assert time.time() - t < 3.0  # returned near the budget, not near 10s
    # a raising fn is swallowed -> (True, None), the caller's cue to use its fallback
    done, r = vs.run_with_time_budget(lambda: (_ for _ in ()).throw(RuntimeError("boom")), 5.0)
    assert done is True and r is None


def test_knowledge_block_falls_back_to_static_docs_when_embedder_cold(monkeypatch):
    """A cold+slow embedder must not stall the turn: within the budget we get the static docs instead."""
    # Embedder reports cold, so the block takes the time-boxed path.
    monkeypatch.setattr(vs, "embedder_is_loaded", lambda: False)

    def _slow_retrieval(*a, **k):
        time.sleep(10)  # simulate a cold embedder download that never returns in time
        return [{"text": "SHOULD-NOT-APPEAR", "source": "x"}]

    monkeypatch.setattr(vs, "get_knowledge_chunks_with_parent", _slow_retrieval, raising=False)
    monkeypatch.setattr(vs, "get_knowledge_chunks_with_sources", _slow_retrieval, raising=False)
    monkeypatch.setattr(vs, "refresh_knowledge_if_changed", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(runtime_safety, "load_knowledge_docs", lambda **k: "STATIC-FALLBACK-DOC")

    cfg = {"use_chroma": True, "knowledge_rag_budget_s": 0.5, "knowledge_chunks_k": 5,
           "knowledge_max_bytes": 4000}
    state: dict = {}
    t = time.time()
    block = _resolve_knowledge_block(
        cfg, goal="Explain the architecture and reasoning approach in detail",
        aspect={"id": "morrigan"}, state=state, _skip_expensive=False,
    )
    elapsed = time.time() - t
    assert elapsed < 3.0, f"knowledge block stalled {elapsed:.1f}s on a cold embedder"
    assert "SHOULD-NOT-APPEAR" not in block          # the slow retrieval was abandoned
    assert "STATIC-FALLBACK-DOC" in block            # degraded to static reference docs


def test_warm_embedder_path_is_inline(monkeypatch):
    """When the embedder is warm, retrieval runs inline (no budget thread) and its chunks are used."""
    monkeypatch.setattr(vs, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(vs, "refresh_knowledge_if_changed", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(
        vs, "get_knowledge_chunks_with_parent",
        lambda *a, **k: [{"text": "WARM-CHUNK", "source": "doc.md"}], raising=False,
    )
    cfg = {"use_chroma": True, "knowledge_rag_budget_s": 0.5, "knowledge_chunks_k": 5}
    state: dict = {}
    block = _resolve_knowledge_block(
        cfg, goal="Explain the architecture in detail", aspect={"id": "morrigan"},
        state=state, _skip_expensive=False,
    )
    assert "WARM-CHUNK" in block
    assert state.get("cited_knowledge_sources") == ["doc.md"]
