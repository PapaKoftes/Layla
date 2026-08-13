"""The knowledge-RAG hot path must never hang the turn on a COLD embedder, and must never spawn an
unmanaged thread that loads torch (a daemon mid-init aborts at interpreter shutdown — exit 134).

Regression for two linked CI failures on test_completion.py::test_workspace_context_appears_in_head:
  1. a 600s hang — a substantive goal triggered RAG, whose first touch DOWNLOADED the embedder mid-test;
  2. exit 134 (SIGABRT at teardown) — an early fix pushed that load onto a daemon thread.

The shipped design: RAG runs ONLY when the embedder is already warm (embedder_is_loaded()). Cold -> use
the static reference docs this turn, no load, no thread. The embedder is warmed out-of-band by the app's
startup warmup. Hermetic: no network, no chromadb.
"""
import runtime_safety
from layla.memory import vector_store as vs
from services.prompts.system_head_builder import _resolve_knowledge_block


def test_cold_embedder_uses_static_docs_without_touching_retrieval(monkeypatch):
    """Cold embedder: no retrieval call at all (so no load/download), degrade to static reference docs."""
    monkeypatch.setattr(vs, "embedder_is_loaded", lambda: False)

    def _boom(*a, **k):  # retrieval must NOT be called while the embedder is cold
        raise AssertionError("retrieval was invoked on a cold embedder — would trigger a blocking load")

    monkeypatch.setattr(vs, "get_knowledge_chunks_with_parent", _boom, raising=False)
    monkeypatch.setattr(vs, "get_knowledge_chunks_with_sources", _boom, raising=False)
    monkeypatch.setattr(runtime_safety, "load_knowledge_docs", lambda **k: "STATIC-FALLBACK-DOC")

    cfg = {"use_chroma": True, "knowledge_chunks_k": 5, "knowledge_max_bytes": 4000}
    state: dict = {}
    block = _resolve_knowledge_block(
        cfg, goal="Explain the architecture and reasoning approach in detail",
        aspect={"id": "morrigan"}, state=state, _skip_expensive=False,
    )
    assert "STATIC-FALLBACK-DOC" in block
    assert state.get("cited_knowledge_sources") in (None, [])  # nothing retrieved, so nothing cited


def test_warm_embedder_path_retrieves_and_cites(monkeypatch):
    """Warm embedder: retrieval runs inline and its chunks + sources land in the head."""
    monkeypatch.setattr(vs, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(vs, "refresh_knowledge_if_changed", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(
        vs, "get_knowledge_chunks_with_parent",
        lambda *a, **k: [{"text": "WARM-CHUNK", "source": "doc.md"}], raising=False,
    )
    cfg = {"use_chroma": True, "knowledge_chunks_k": 5}
    state: dict = {}
    block = _resolve_knowledge_block(
        cfg, goal="Explain the architecture in detail", aspect={"id": "morrigan"},
        state=state, _skip_expensive=False,
    )
    assert "WARM-CHUNK" in block
    assert state.get("cited_knowledge_sources") == ["doc.md"]


def test_embedder_is_loaded_reflects_module_state(monkeypatch):
    monkeypatch.setattr(vs, "_embedder", None, raising=False)
    assert vs.embedder_is_loaded() is False
    monkeypatch.setattr(vs, "_embedder", object(), raising=False)
    assert vs.embedder_is_loaded() is True
