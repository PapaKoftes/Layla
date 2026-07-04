# -*- coding: utf-8 -*-
"""
Reranker service — improve retrieval quality by scoring document relevance.

Backend order (auto): FlashRank (lightweight ONNX cross-encoder, no torch — the potato-path
default, BL-103) → sentence-transformers CrossEncoder (heavier, higher quality) → BM25 (always
available, zero-dep). Model instances are cached at module level, so a rerank call never
re-loads the model (the previous version instantiated a CrossEncoder on EVERY call).

Config:
    reranker_backend   "auto" | "flashrank" | "cross_encoder" | "bm25"  (default "auto")

Usage:
    from services.retrieval.reranker import rerank
    ranked = rerank("fastapi async patterns", documents, top_k=5)
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter

logger = logging.getLogger("layla")

# Cached model instances + a set of backends we've already found unavailable (skip retry).
_flashrank_ranker = None
_cross_encoder = None
_unavailable: set[str] = set()


def reset_reranker_cache() -> None:
    """Drop cached model instances + availability memo (tests / after a config change)."""
    global _flashrank_ranker, _cross_encoder
    _flashrank_ranker = None
    _cross_encoder = None
    _unavailable.clear()


def _backend_order(pref: str) -> list[str]:
    pref = (pref or "auto").lower()
    if pref == "flashrank":
        return ["flashrank", "bm25"]
    if pref == "cross_encoder":
        return ["cross_encoder", "bm25"]
    if pref == "bm25":
        return ["bm25"]
    return ["flashrank", "cross_encoder", "bm25"]  # auto: lightest capable backend first


def _get_flashrank():
    global _flashrank_ranker
    if _flashrank_ranker is not None:
        return _flashrank_ranker
    if "flashrank" in _unavailable:
        return None
    try:
        from flashrank import Ranker
        _flashrank_ranker = Ranker(max_length=512)  # default small model; cached from here on
        return _flashrank_ranker
    except Exception as exc:
        _unavailable.add("flashrank")
        logger.debug("reranker: flashrank unavailable (%s)", exc)
        return None


def _flashrank_rerank(query: str, documents: list[str], top_k: int):
    ranker = _get_flashrank()
    if ranker is None:
        return None
    try:
        from flashrank import RerankRequest
        req = RerankRequest(query=query, passages=[{"id": i, "text": d} for i, d in enumerate(documents)])
        results = ranker.rerank(req)  # [{id, text, score}] sorted desc
        return [
            {"content": r["text"], "score": float(r["score"]), "original_index": int(r["id"])}
            for r in results[:top_k]
        ]
    except Exception as exc:
        logger.debug("reranker: flashrank failed (%s)", exc)
        return None


def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder
    if "cross_encoder" in _unavailable:
        return None
    try:
        from sentence_transformers import CrossEncoder
        _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return _cross_encoder
    except Exception as exc:
        _unavailable.add("cross_encoder")
        logger.debug("reranker: cross-encoder unavailable (%s)", exc)
        return None


def _cross_encoder_rerank(query: str, documents: list[str], top_k: int):
    model = _get_cross_encoder()
    if model is None:
        return None
    try:
        scores = model.predict([(query, doc) for doc in documents])
        ranked = sorted(
            [{"content": doc, "score": float(s), "original_index": i}
             for i, (doc, s) in enumerate(zip(documents, scores))],
            key=lambda x: -x["score"],
        )
        return ranked[:top_k]
    except Exception as exc:
        logger.debug("reranker: cross-encoder failed (%s)", exc)
        return None


def rerank(query: str, documents: list[str], *, top_k: int = 5, backend: str | None = None, cfg: dict | None = None) -> list[dict]:
    """
    Rerank documents by relevance to query.

    Returns list of {content, score, original_index} sorted by descending score. Tries the
    configured backend chain (auto: flashrank → cross-encoder → bm25); each unavailable backend
    is skipped and memoized so the next call goes straight to the working one.
    """
    if not documents:
        return []
    if not query.strip():
        return [{"content": d, "score": 0.0, "original_index": i} for i, d in enumerate(documents[:top_k])]

    pref = backend or (cfg or {}).get("reranker_backend", "auto")
    for b in _backend_order(pref):
        if b == "flashrank":
            r = _flashrank_rerank(query, documents, top_k)
            if r is not None:
                return r
        elif b == "cross_encoder":
            r = _cross_encoder_rerank(query, documents, top_k)
            if r is not None:
                return r
        elif b == "bm25":
            return _bm25_rerank(query, documents, top_k)
    return _bm25_rerank(query, documents, top_k)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer, lowercased."""
    return re.findall(r"\w+", text.lower())


def _bm25_rerank(query: str, documents: list[str], top_k: int) -> list[dict]:
    """
    BM25-style keyword scoring fallback.

    k1=1.5, b=0.75 — standard BM25 parameters.
    """
    q_tokens = _tokenize(query)
    if not q_tokens:
        return [{"content": d, "score": 0.0, "original_index": i} for i, d in enumerate(documents[:top_k])]

    # Document frequency for IDF
    n_docs = len(documents)
    doc_tokens = [_tokenize(d) for d in documents]
    avg_dl = sum(len(dt) for dt in doc_tokens) / max(n_docs, 1)

    # DF: number of documents containing each query term
    df: Counter = Counter()
    for dt in doc_tokens:
        dt_set = set(dt)
        for qt in q_tokens:
            if qt in dt_set:
                df[qt] += 1

    k1 = 1.5
    b = 0.75

    scored: list[dict] = []
    for i, dt in enumerate(doc_tokens):
        score = 0.0
        tf_counter = Counter(dt)
        dl = len(dt)
        for qt in q_tokens:
            tf = tf_counter.get(qt, 0)
            if tf == 0:
                continue
            idf = math.log((n_docs - df[qt] + 0.5) / (df[qt] + 0.5) + 1.0)
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avg_dl, 1)))
            score += idf * tf_norm
        scored.append({"content": documents[i], "score": round(score, 4), "original_index": i})

    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]
