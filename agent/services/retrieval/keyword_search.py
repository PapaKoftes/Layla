"""
BM25-lite for ephemeral corpora (file chunks, scratch lists).

Do not use for persistent learnings — those use layla.memory.vector_store BM25 index.
"""
from __future__ import annotations

from typing import Any


class EphemeralBM25Index:
    """Tiny inverted-style BM25 (rank_bm25) over doc_ids + texts."""

    def __init__(self, doc_ids: list[str], texts: list[str]) -> None:
        self._ids = list(doc_ids)
        self._texts = list(texts)
        self._bm25: Any = None
        self._tok: list[list[str]] = []
        self._rebuild()

    def _rebuild(self) -> None:
        self._tok = [(t or "").lower().split() for t in self._texts]
        try:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi(self._tok) if self._tok else None
        except Exception:
            self._bm25 = None

    def score_query(self, query: str) -> dict[str, float]:
        """Return normalized scores in [0,1] keyed by doc_id."""
        if not self._bm25 or not query.strip():
            return {}
        q = query.lower().split()
        scores = self._bm25.get_scores(q)
        if not scores:
            return {}
        mx = max(scores)
        mn = min(scores)
        span = mx - mn if mx != mn else 1.0
        out: dict[str, float] = {}
        for i, sid in enumerate(self._ids):
            if i >= len(scores):
                break
            norm = (scores[i] - mn) / span if span else 1.0
            out[str(sid)] = max(0.0, min(1.0, float(norm)))
        return out


def build_index(doc_ids: list[str], texts: list[str]) -> EphemeralBM25Index:
    return EphemeralBM25Index(doc_ids, texts)
