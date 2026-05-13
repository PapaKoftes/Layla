# -*- coding: utf-8 -*-
"""
Reranker service — improve retrieval quality by scoring document relevance.

Uses cross-encoder model when sentence-transformers is available;
falls back to BM25-style keyword scoring.

Usage:
    from services.reranker import rerank
    ranked = rerank("fastapi async patterns", documents, top_k=5)
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter

logger = logging.getLogger("layla")


def rerank(query: str, documents: list[str], *, top_k: int = 5) -> list[dict]:
    """
    Rerank documents by relevance to query.

    Returns list of {content, score, original_index} sorted by descending score.
    Uses cross-encoder if sentence-transformers available, otherwise BM25.
    """
    if not documents:
        return []
    if not query.strip():
        return [{"content": d, "score": 0.0, "original_index": i} for i, d in enumerate(documents[:top_k])]

    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs)
        ranked = sorted(
            [{"content": doc, "score": float(s), "original_index": i}
             for i, (doc, s) in enumerate(zip(documents, scores))],
            key=lambda x: -x["score"],
        )
        return ranked[:top_k]
    except ImportError:
        logger.debug("reranker: sentence-transformers not available, using BM25 fallback")
    except Exception as exc:
        logger.debug("reranker: cross-encoder failed, using BM25 fallback: %s", exc)

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
