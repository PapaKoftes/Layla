"""Cross-encoder + MMR reranking, split from vector_store.py (BL-027).

Self-contained: its own cross-encoder model cache; embeddings come from vector_store via a
lazy import inside mmr_rerank, so this module imports nothing from vector_store at load time
and vector_store re-exports these names without a cycle.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


_cross_encoder = None
_cross_encoder_failed = False  # don't retry after download failure
_bge_cross_encoder = None
_bge_cross_encoder_model: str | None = None
_bge_cross_encoder_failed = False


def _get_bge_cross_encoder(model_name: str):
    """Optional BGE reranker (sentence_transformers CrossEncoder). Separate from default CE."""
    global _bge_cross_encoder, _bge_cross_encoder_model, _bge_cross_encoder_failed
    if _bge_cross_encoder_failed:
        return None
    if _bge_cross_encoder is not None and _bge_cross_encoder_model == model_name:
        return _bge_cross_encoder
    try:
        from sentence_transformers import CrossEncoder

        _bge_cross_encoder = CrossEncoder(model_name)
        _bge_cross_encoder_model = model_name
        return _bge_cross_encoder
    except Exception:
        _bge_cross_encoder_failed = True
        return None


def _get_cross_encoder():
    global _cross_encoder, _cross_encoder_failed
    if _cross_encoder_failed:
        return None
    if _cross_encoder is not None:
        return _cross_encoder
    try:
        from sentence_transformers import CrossEncoder
        _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        _cross_encoder_failed = True
    return _cross_encoder


def mmr_rerank(query: str, docs: list[dict], k: int = 5, lambda_: float = 0.7) -> list[dict]:
    """
    Maximal Marginal Relevance: balance relevance and diversity.
    lambda_=0.7: 70% relevance, 30% diversity. Higher lambda = more relevance, less diversity.
    """
    if not docs or k <= 0:
        return docs[:k]
    from layla.memory.vector_store import embed, embed_batch  # BL-027: lazy, avoids import cycle
    import numpy as np
    query_vec = embed(query)
    contents = [(d.get("content") or d.get("text") or "")[:512] for d in docs]
    if not any(c for c in contents):
        return docs[:k]
    doc_vecs = embed_batch(contents)
    selected: list[int] = []
    remaining = list(range(len(docs)))

    def _sim(a: Any, b: Any) -> float:
        return float(np.dot(a, b))  # cosine for normalized vecs

    for _ in range(min(k, len(docs))):
        best_idx = -1
        best_score = -1e9
        for i in remaining:
            rel = _sim(query_vec, doc_vecs[i])
            div = max(_sim(doc_vecs[i], doc_vecs[j]) for j in selected) if selected else 0.0
            score = lambda_ * rel - (1 - lambda_) * div
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx < 0:
            break
        selected.append(best_idx)
        remaining.remove(best_idx)
    return [docs[i] for i in selected]


def rerank(query: str, docs: list[dict], k: int = 5) -> list[dict]:
    """
    Rerank retrieved docs with a cross-encoder (query, doc) pair scorer.
    Falls back to original order if model unavailable.
    ~30ms for 20 docs on CPU — well worth the accuracy gain.
    When use_bge_reranker + bge_reranker_model are set, tries BGE CrossEncoder first.
    """
    if not docs:
        return docs
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        if cfg.get("use_bge_reranker"):
            mname = (cfg.get("bge_reranker_model") or "").strip()
            if mname:
                bce = _get_bge_cross_encoder(mname)
                if bce is not None:
                    pairs = [(query, (d.get("content") or d.get("text") or "")[:512]) for d in docs]
                    scores = bce.predict(pairs, show_progress_bar=False)
                    ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
                    return [d for _, d in ranked[:k]]
    except Exception as _exc:
        logger.debug("vector_store:L396: %s", _exc, exc_info=False)
    ce = _get_cross_encoder()
    if ce is None:
        return docs[:k]
    try:
        pairs = [(query, (d.get("content") or d.get("text") or "")[:512]) for d in docs]
        scores = ce.predict(pairs, show_progress_bar=False)
        ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
        return [d for _, d in ranked[:k]]
    except Exception:
        return docs[:k]
