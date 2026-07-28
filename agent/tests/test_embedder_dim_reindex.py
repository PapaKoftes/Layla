# -*- coding: utf-8 -*-
"""
ST-1 regression: a stored vector is only valid for the embedder that produced it.

When the embedding model (and therefore the vector dimension) changes, the query layer
filters out every stale-dim row, so the whole knowledge base silently returns nothing.
The index must detect the model swap and re-embed. Two mechanisms guard this:

  1. `_knowledge_dir_fingerprint` folds the active embedder identity in, so a model swap
     flips the fingerprint and forces a refresh even when no file changed.
  2. `index_knowledge_docs` namespaces each chunk's content_hash by the embedder identity,
     so the incremental upsert re-embeds unchanged content under a new model.

This test pins mechanism (1) directly (it needs no embedder to run) and documents (2).
"""
from __future__ import annotations

from pathlib import Path

import layla.memory.vector_store as vs


def test_fingerprint_changes_when_embedder_model_changes(tmp_path: Path) -> None:
    kd = tmp_path / "knowledge"
    kd.mkdir()
    (kd / "note.md").write_text("stable content that never changes", encoding="utf-8")

    orig_name = vs._current_model_name
    orig_dim = vs._embedder_dim
    try:
        vs._current_model_name = "all-MiniLM-L6-v2"
        vs._embedder_dim = 384
        fp_a = vs._knowledge_dir_fingerprint(kd)

        # Same files, different embedder -> fingerprint MUST differ so a refresh fires.
        vs._current_model_name = "nomic-ai/nomic-embed-text-v1.5"
        vs._embedder_dim = 768
        fp_b = vs._knowledge_dir_fingerprint(kd)

        assert fp_a != fp_b, "embedder swap must change the knowledge fingerprint"

        # Same embedder + same files -> stable fingerprint (no needless reindex).
        fp_b2 = vs._knowledge_dir_fingerprint(kd)
        assert fp_b == fp_b2
    finally:
        vs._current_model_name = orig_name
        vs._embedder_dim = orig_dim
