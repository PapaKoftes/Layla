"""Tests for the compiler-free vector store fallback (REQ-72, A3).

Proves the SQLite+NumPy FallbackCollection is a faithful drop-in for the chromadb
Collection API Layla uses: correct cosine nearest-neighbor, Chroma-shaped nested
query output, get/delete/count/upsert/where-filter, and on-disk persistence — all
with no chromadb and no C++ toolchain. numpy-only; runs on the friend's tier.
"""
import sys
from pathlib import Path

import numpy as np

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.memory.fallback_store import (  # noqa: E402
    FallbackCollection,
    get_fallback_collection,
    reset_fallback_cache,
)


def _coll(tmp_path, name="learnings"):
    return FallbackCollection(name, tmp_path / f"{name}.sqlite")


def test_add_then_nearest_neighbor_is_correct(tmp_path):
    c = _coll(tmp_path)
    c.add(ids=["a", "b", "c"],
          embeddings=[[1, 0, 0], [0, 1, 0], [0.9, 0.1, 0]],
          metadatas=[{"t": "x"}, {"t": "y"}, {"t": "z"}])
    # query near [1,0,0] → 'a' (identical) then 'c' (close), not 'b' (orthogonal)
    res = c.query(query_embeddings=[[1, 0, 0]], n_results=2)
    assert res["ids"] == [["a", "c"]], res["ids"]          # chroma nested shape
    assert res["distances"][0][0] < 1e-5                   # 'a' ~ identical
    assert res["distances"][0][0] <= res["distances"][0][1]  # sorted nearest-first
    assert res["metadatas"][0][0]["t"] == "x"


def test_query_shape_matches_chroma(tmp_path):
    c = _coll(tmp_path)
    c.add(ids=["a"], embeddings=[[1.0, 2.0]], metadatas=[{"k": 1}], documents=["doc-a"])
    res = c.query(query_embeddings=[[1.0, 2.0]], n_results=5,
                  include=["metadatas", "distances", "documents"])
    # every value is a list-of-lists (one inner list per query embedding)
    for key in ("ids", "distances", "metadatas", "documents"):
        assert isinstance(res[key], list) and isinstance(res[key][0], list)
    assert res["documents"][0][0] == "doc-a"


def test_empty_collection_query_is_safe(tmp_path):
    c = _coll(tmp_path)
    res = c.query(query_embeddings=[[1, 2, 3]], n_results=5)
    assert res["ids"] == [[]] and res["distances"] == [[]]


def test_get_count_delete_upsert(tmp_path):
    c = _coll(tmp_path)
    c.add(ids=["x", "y"], embeddings=[[1, 0], [0, 1]], metadatas=[{"n": 1}, {"n": 2}])
    assert c.count() == 2
    got = c.get(ids=["x"], include=["metadatas", "embeddings"])
    assert got["ids"] == ["x"] and got["metadatas"][0]["n"] == 1
    assert len(got["embeddings"][0]) == 2
    # upsert overwrites
    c.upsert(ids=["x"], embeddings=[[2, 2]], metadatas=[{"n": 9}])
    assert c.get(ids=["x"])["metadatas"][0]["n"] == 9
    assert c.count() == 2
    c.delete(ids=["x"])
    assert c.count() == 1


def test_where_filter_on_query_and_get(tmp_path):
    c = _coll(tmp_path)
    c.add(ids=["a", "b"], embeddings=[[1, 0], [1, 0]],
          metadatas=[{"kind": "learning"}, {"kind": "knowledge"}])
    res = c.query(query_embeddings=[[1, 0]], n_results=5, where={"kind": "learning"})
    assert res["ids"] == [["a"]]
    got = c.get(where={"kind": {"$eq": "knowledge"}})
    assert got["ids"] == ["b"]


def test_update_metadata_only(tmp_path):
    c = _coll(tmp_path)
    c.add(ids=["a"], embeddings=[[1, 0]], metadatas=[{"score": 1}])
    c.update(ids=["a"], metadatas=[{"score": 5}])
    assert c.get(ids=["a"])["metadatas"][0]["score"] == 5


def test_peek_returns_embeddings(tmp_path):
    c = _coll(tmp_path)
    c.add(ids=["a"], embeddings=[[1, 0, 0]], metadatas=[{}])
    peek = c.peek(limit=1)
    assert peek["ids"] == ["a"] and len(peek["embeddings"][0]) == 3


def test_persistence_across_reopen(tmp_path):
    path = tmp_path / "p.sqlite"
    c1 = FallbackCollection("learnings", path)
    c1.add(ids=["a"], embeddings=[[1, 2, 3]], metadatas=[{"keep": True}])
    del c1
    c2 = FallbackCollection("learnings", path)  # reopen same file
    assert c2.count() == 1
    assert c2.get(ids=["a"])["metadatas"][0]["keep"] is True


def test_factory_is_singleton_per_name(tmp_path):
    reset_fallback_cache()
    a = get_fallback_collection("learnings", tmp_path)
    b = get_fallback_collection("learnings", tmp_path)
    k = get_fallback_collection("knowledge", tmp_path)
    assert a is b and a is not k


def test_metadata_content_used_as_document_fallback(tmp_path):
    c = _coll(tmp_path)
    c.add(ids=["a"], embeddings=[[1, 0]], metadatas=[{"content": "hello"}])
    assert c.get(ids=["a"], include=["documents"])["documents"][0] == "hello"


def test_vector_store_uses_fallback_when_chroma_absent(tmp_path, monkeypatch):
    """End-to-end: with chromadb forced absent, vector_store's PUBLIC api
    (add_vector + search_similar) still stores and retrieves — memory works on a
    compiler-less box instead of silently turning off."""
    import layla.memory.fallback_store as fb
    import layla.memory.vector_store as vs

    monkeypatch.setattr(vs, "_real_chroma", lambda: False)   # simulate no chromadb
    monkeypatch.setattr(vs, "CHROMA_PATH", tmp_path)
    monkeypatch.setattr(vs, "_chroma_collection", None)
    fb.reset_fallback_cache()

    assert vs._vector_enabled() is True
    vs.add_vector(np.array([1, 0, 0], dtype="float32"), {"content": "alpha"})
    vs.add_vector(np.array([0, 1, 0], dtype="float32"), {"content": "beta"})
    vs.add_vector(np.array([0.95, 0.05, 0], dtype="float32"), {"content": "alpha-ish"})

    hits = vs.search_similar(np.array([1, 0, 0], dtype="float32"), k=2)
    contents = [(h.get("metadata") or h).get("content") if isinstance(h.get("metadata") or h, dict)
                else None for h in hits]
    assert len(hits) == 2
    assert contents[0] == "alpha"            # nearest is the identical vector
    assert "alpha-ish" in contents           # second nearest, not the orthogonal 'beta'
    assert "beta" not in contents


def test_disabled_flag_turns_memory_off(monkeypatch):
    """LAYLA_CHROMA_DISABLED=1 disables vector memory entirely (not even fallback)."""
    import layla.memory.vector_store as vs
    monkeypatch.setenv("LAYLA_CHROMA_DISABLED", "1")
    assert vs._vector_enabled() is False


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
