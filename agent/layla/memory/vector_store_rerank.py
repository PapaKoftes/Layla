"""Cross-encoder + MMR reranking, split from vector_store.py (BL-027).

Self-contained: its own cross-encoder model cache; embeddings come from vector_store via a
lazy import inside mmr_rerank, so this module imports nothing from vector_store at load time
and vector_store re-exports these names without a cycle.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
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


def _doc_text(d: dict) -> str:
    return (d.get("content") or d.get("text") or "")


def _tokenize(text: str) -> list[str]:
    """Whitespace + punctuation tokenizer, lowercased."""
    return re.findall(r"\w+", text.lower())


def _bm25_rerank(query: str, docs: list[dict], k: int) -> list[dict]:
    """Zero-dependency BM25 keyword backstop (k1=1.5, b=0.75 — standard parameters).

    Ported from services/retrieval/reranker.py, adapted to this module's contract: it takes and
    returns the caller's doc dicts (reordered), rather than the {content,score,original_index}
    records the service version builds.

    This exists so that a missing/uncached cross-encoder degrades to *keyword* ranking instead
    of to no ranking at all. Returning the retriever's arbitrary first k docs, as this module
    previously did, is indistinguishable from success at the call site.
    """
    q_tokens = _tokenize(query)
    doc_tokens = [_tokenize(_doc_text(d)[:512]) for d in docs]
    # Nothing to score against: an empty query, or docs with no extractable text. Order is
    # genuinely undefined here, so preserve the retriever's own ranking.
    if not q_tokens or not any(doc_tokens):
        return docs[:k]

    n_docs = len(docs)
    avg_dl = sum(len(dt) for dt in doc_tokens) / max(n_docs, 1)

    df: Counter = Counter()
    for dt in doc_tokens:
        dt_set = set(dt)
        for qt in q_tokens:
            if qt in dt_set:
                df[qt] += 1

    k1, b = 1.5, 0.75
    scored: list[tuple[float, int]] = []
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
        scored.append((score, i))

    scored.sort(key=lambda x: (-x[0], x[1]))  # stable: ties keep retriever order
    return [docs[i] for _, i in scored[:k]]


def mmr_rerank(query: str, docs: list[dict], k: int = 5, lambda_: float = 0.7) -> list[dict]:
    """
    Maximal Marginal Relevance: balance relevance and diversity.
    lambda_=0.7: 70% relevance, 30% diversity. Higher lambda = more relevance, less diversity.
    """
    if not docs or k <= 0:
        return docs[:k]
    import numpy as np

    from layla.memory.vector_store import embed, embed_batch  # BL-027: lazy, avoids import cycle
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
        # Degraded path A: sentence-transformers absent, or the model was never cached and this
        # machine is offline (there is no local_files_only anywhere, so a first run with no
        # network lands here). Previously returned docs[:k] — the retriever's arbitrary order,
        # silently, with nothing distinguishing it from a real ranking.
        logger.warning(
            "rerank: cross-encoder unavailable (sentence-transformers missing, or model "
            "'cross-encoder/ms-marco-MiniLM-L-6-v2' not cached and no network); "
            "falling back to BM25 keyword reranking for %d docs",
            len(docs),
        )
        return _bm25_rerank(query, docs, k)
    try:
        pairs = [(query, _doc_text(d)[:512]) for d in docs]
        scores = ce.predict(pairs, show_progress_bar=False)
        ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
        return [d for _, d in ranked[:k]]
    except Exception as exc:
        # Degraded path B: the model loaded but scoring blew up (OOM, bad input, torch fault).
        # This except logged NOTHING at all before.
        logger.warning(
            "rerank: cross-encoder scoring failed (%s); falling back to BM25 keyword "
            "reranking for %d docs", exc, len(docs),
        )
        return _bm25_rerank(query, docs, k)
