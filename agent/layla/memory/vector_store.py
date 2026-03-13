"""
Vector store for semantic search over learnings.
Uses ChromaDB as the sole persistent store (FAISS removed).
Embedding model: nomic-embed-text (768 dim) via sentence-transformers,
with fallback to all-MiniLM-L6-v2 (384 dim) if nomic is unavailable.
"""
import uuid
import numpy as np
import hashlib
import time
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent
CHROMA_PATH = MEMORY_DIR / "chroma_db"

_embedder = None
_embedder_dim: int = 768  # set when embedder loads
_chroma_collection = None
_knowledge_fingerprint: str = ""
_knowledge_last_check_ts: float = 0.0

# Small LRU cache: avoid re-embedding identical strings during a single agent loop
import functools as _functools  # noqa: E402
_EMBED_CACHE_SIZE = 256


def _get_embedder():
    """
    Load the sentence-transformer model once and configure it for speed:
    - nomic-embed-text-v1.5 (768d, best quality) with all-MiniLM fallback
    - int8 quantization via quantize_model when available (2× faster CPU, ~same quality)
    - half-precision on GPU via .half() (2× VRAM reduction, faster matmul)
    """
    global _embedder, _embedder_dim
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        import logging
        log = logging.getLogger("layla")
        try:
            model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)
            _embedder_dim = 768
            log.info("Embedding model: nomic-embed-text-v1.5 (768d)")
        except Exception:
            model = SentenceTransformer("all-MiniLM-L6-v2")
            _embedder_dim = 384
            log.info("Embedding model: all-MiniLM-L6-v2 (384d) [nomic unavailable]")
        # Quantize to int8 for faster CPU inference when torch is available
        try:
            import torch
            if torch.cuda.is_available():
                model = model.half()  # float16 on GPU: 2× VRAM reduction
                log.info("Embedder: float16 on GPU")
            else:
                # Dynamic int8 quantization for CPU
                model[0].auto_model = torch.quantization.quantize_dynamic(
                    model[0].auto_model, {torch.nn.Linear}, dtype=torch.qint8
                )
                log.info("Embedder: int8 quantized on CPU")
        except Exception:
            pass
        _embedder = model
    return _embedder


@_functools.lru_cache(maxsize=_EMBED_CACHE_SIZE)
def _embed_cached(text: str) -> tuple:
    """Cached embedding. Returns tuple (for hashability). Use embed() externally."""
    model = _get_embedder()
    vec = model.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
    return tuple(vec.astype("float32").tolist())


def embed_batch(texts: list[str]) -> list:
    """Embed multiple texts in one forward pass — much faster than one-by-one."""
    if not texts:
        return []
    model = _get_embedder()
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True, batch_size=32)
    return [v.astype("float32") for v in vecs]


def _get_chroma_collection():
    global _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    _chroma_collection = client.get_or_create_collection(
        name="learnings",
        metadata={"hnsw:space": "cosine"},
    )
    return _chroma_collection


def _use_chroma() -> bool:
    """Return True if chromadb is importable and available."""
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


# ─── Public API ─────────────────────────────────────────────────────────────

def embed(text: str) -> np.ndarray:
    """Return a normalized float32 embedding. Results are LRU-cached per text."""
    return np.array(_embed_cached(text), dtype="float32")


def add_vector(vec: np.ndarray, metadata: dict) -> str:
    """Add a vector + metadata to ChromaDB. Returns the document ID."""
    uid = str(uuid.uuid4())
    try:
        coll = _get_chroma_collection()
        meta_flat = {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in metadata.items()}
        coll.add(ids=[uid], embeddings=[vec.astype(float).tolist()], metadatas=[meta_flat])
    except Exception:
        pass
    return uid


def upsert_vector(doc_id: str, vec: np.ndarray, metadata: dict) -> None:
    """Upsert a vector by id. Used when re-embedding distilled learnings."""
    try:
        coll = _get_chroma_collection()
        meta_flat = {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in metadata.items()}
        coll.upsert(ids=[doc_id], embeddings=[vec.astype(float).tolist()], metadatas=[meta_flat])
    except Exception:
        pass


def delete_vectors_by_ids(ids: list[str]) -> None:
    """Remove vectors from ChromaDB by id list."""
    if not ids:
        return
    try:
        coll = _get_chroma_collection()
        coll.delete(ids=ids)
    except Exception:
        pass


_knowledge_collection = None

def _get_knowledge_collection():
    global _knowledge_collection
    if _knowledge_collection is not None:
        return _knowledge_collection
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    _knowledge_collection = client.get_or_create_collection(name="knowledge", metadata={"hnsw:space": "cosine"})
    return _knowledge_collection


def search_similar(query_vec: np.ndarray, k: int = 5) -> list:
    """Return up to k metadata dicts from ChromaDB learnings collection."""
    try:
        coll = _get_chroma_collection()
        if coll.count() == 0:
            return []
        n = min(k, coll.count())
        res = coll.query(
            query_embeddings=[query_vec.astype(float).tolist()],
            n_results=n,
            include=["metadatas"],
        )
        if res and res.get("metadatas") and res["metadatas"][0]:
            return list(res["metadatas"][0])
    except Exception:
        pass
    return []


# ─── BM25 hybrid search ──────────────────────────────────────────────────────

_bm25_index = None
_bm25_docs: list[dict] = []
_bm25_doc_count: int = -1


def _get_bm25_index():
    """Lazily build BM25 index over all learnings. Rebuilt when count changes."""
    global _bm25_index, _bm25_docs, _bm25_doc_count
    try:
        from layla.memory.db import get_recent_learnings
        docs = get_recent_learnings(n=2000)
        if len(docs) == _bm25_doc_count and _bm25_index is not None:
            return _bm25_index, _bm25_docs
        from rank_bm25 import BM25Okapi
        tokenized = [d["content"].lower().split() for d in docs]
        _bm25_index = BM25Okapi(tokenized)
        _bm25_docs = docs
        _bm25_doc_count = len(docs)
        return _bm25_index, _bm25_docs
    except Exception:
        return None, []


def _reciprocal_rank_fusion(lists: list[list[dict]], k: int = 5, rrf_k: int = 60) -> list[dict]:
    """Fuse multiple ranked result lists using Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    content_map: dict[str, dict] = {}
    for ranked_list in lists:
        for i, item in enumerate(ranked_list):
            key = (item.get("content") or "")[:120]
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + i + 1)
            if key not in content_map:
                content_map[key] = item
    sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [content_map[kk] for kk in sorted_keys[:k]]


def search_hybrid(query: str, k: int = 5) -> list[dict]:
    """
    Hybrid BM25 + dense vector search fused via Reciprocal Rank Fusion.
    BM25 catches exact keyword/code matches; vector catches semantic similarity.
    Falls back gracefully to pure vector search if BM25 index is unavailable.
    """
    query_vec = embed(query)
    vector_results = search_similar(query_vec, k=k * 3)

    bm25_results: list[dict] = []
    try:
        bm25, docs = _get_bm25_index()
        if bm25 and docs:
            scores = bm25.get_scores(query.lower().split())
            top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: k * 3]
            bm25_results = [docs[i] for i in top_idx if scores[i] > 0]
    except Exception:
        pass

    if not bm25_results:
        return vector_results[:k]
    return _reciprocal_rank_fusion([vector_results, bm25_results], k=k)


# ─── Cross-encoder reranking ─────────────────────────────────────────────────

_cross_encoder = None
_cross_encoder_failed = False  # don't retry after download failure


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


def rerank(query: str, docs: list[dict], k: int = 5) -> list[dict]:
    """
    Rerank retrieved docs with a cross-encoder (query, doc) pair scorer.
    Falls back to original order if model unavailable.
    ~30ms for 20 docs on CPU — well worth the accuracy gain.
    """
    if not docs:
        return docs
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


# ─── HyDE — Hypothetical Document Embeddings ─────────────────────────────────

def search_with_hyde(query: str, k: int = 5, fallback: bool = True) -> list[dict]:
    """
    HyDE: generate a short hypothetical answer, embed it, search with that vector.
    Dramatically improves recall when query phrasing doesn't match document language.
    Falls back to standard dense search if LLM is unavailable or too slow.
    """
    try:
        from services.llm_gateway import run_completion
        hyp_prompt = (
            f"Write a concise, factual 2-3 sentence answer to this question. "
            f"Be specific and technical if relevant.\n\nQuestion: {query}"
        )
        result = run_completion(hyp_prompt, max_tokens=120, temperature=0.0)
        if isinstance(result, dict):
            hyp = ((result.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        else:
            hyp = ""
        if hyp and len(hyp.strip()) > 20:
            hyde_vec = embed(hyp.strip())
            results = search_similar(hyde_vec, k=k * 2)
            if results:
                # Fuse with original query results for robustness
                orig = search_similar(embed(query), k=k * 2)
                return _reciprocal_rank_fusion([results, orig], k=k)
    except Exception:
        pass
    if fallback:
        return search_similar(embed(query), k=k)
    return []


# ─── Parent-document retrieval ────────────────────────────────────────────────

def get_knowledge_chunks_with_parent(query: str, k: int = 5) -> list[dict]:
    """
    Retrieve knowledge chunks and enrich with surrounding parent document context.
    Each chunk's metadata carries a 'source' field; we load the full source file
    and return the surrounding paragraph (up to 1200 chars) around the matched chunk.
    """

    # Get initial chunks from standard search
    try:
        chunks = get_knowledge_chunks_with_sources(query, k=k * 2)
    except Exception:
        chunks = []

    enriched = []
    seen_sources: dict[str, str] = {}

    for chunk in chunks[:k]:
        source = chunk.get("source", "")
        text = chunk.get("text", "")
        if not source or not text:
            enriched.append(chunk)
            continue
        # Try to read the parent file
        if source not in seen_sources:
            try:
                # Look up path relative to knowledge/ dir
                from pathlib import Path as _P
                knowledge_dir = _P(__file__).resolve().parent.parent.parent.parent / "knowledge"
                full_path = knowledge_dir / source
                if full_path.exists():
                    seen_sources[source] = full_path.read_text(encoding="utf-8", errors="replace")
                else:
                    seen_sources[source] = ""
            except Exception:
                seen_sources[source] = ""
        parent_text = seen_sources.get(source, "")
        if parent_text and text in parent_text:
            # Find chunk in parent, extract ±600 chars of surrounding context
            idx = parent_text.find(text)
            start = max(0, idx - 400)
            end = min(len(parent_text), idx + len(text) + 400)
            extended = parent_text[start:end].strip()
            enriched.append({**chunk, "text": extended})
        else:
            enriched.append(chunk)

    return enriched


# ─── Full search pipeline: hybrid → rerank → parent context ──────────────────

def search_memories_full(query: str, k: int = 5, use_rerank: bool = True) -> list[dict]:
    """
    Full memory search pipeline:
      1. Hybrid BM25 + vector (RRF fusion)
      2. FTS5 keyword results merged in
      3. Cross-encoder reranking
    Returns top-k most relevant learnings.
    """
    # Step 1: hybrid vector + BM25
    results = search_hybrid(query, k=k * 3)

    # Step 2: merge FTS5 keyword results
    try:
        from layla.memory.db import search_learnings_fts
        fts_hits = search_learnings_fts(query, n=k * 2)
        if fts_hits:
            results = _reciprocal_rank_fusion([results, fts_hits], k=k * 3)
    except Exception:
        pass

    # Step 3: cross-encoder rerank
    if use_rerank:
        results = rerank(query, results, k=k)
    else:
        results = results[:k]
    return results


def _read_pdf_text(path: Path) -> str:
    """Extract text from a PDF file. Returns '' if pypdf not available or on error."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages[:50]:
            t = page.extract_text()
            if t:
                parts.append(t)
        return "\n\n".join(parts) if parts else ""
    except Exception:
        return ""


def index_knowledge_docs(knowledge_dir: Path) -> None:
    """Chunk and index all .md, .txt, and .pdf under knowledge_dir into Chroma 'knowledge' collection. No-op if not use_chroma.
    Supports optional front matter: ---\\npriority: core|support|flavor\\ndomain: coding|personality|research\\n---
    If missing, priority=support. Excludes paths containing .identity (Lilith-only).
    Incremental: avoids duplication and preserves unchanged embeddings via content_hash."""
    global _knowledge_fingerprint
    if not _use_chroma():
        return
    try:
        coll = _get_knowledge_collection()

        # Existing hashes for dedupe / no-op updates
        existing_hash: dict[str, str] = {}
        existing_ids: set[str] = set()
        try:
            got = coll.get(include=["metadatas"])
            ids = got.get("ids") or []
            metas = got.get("metadatas") or []
            for i, cid in enumerate(ids):
                existing_ids.add(cid)
                m = metas[i] if i < len(metas) else {}
                if isinstance(m, dict) and m.get("content_hash"):
                    existing_hash[cid] = str(m.get("content_hash"))
        except Exception:
            pass

        chunks: list[tuple[str, str, dict]] = []
        for ext in ("*.md", "*.txt", "*.pdf"):
            for f in sorted(knowledge_dir.rglob(ext)):
                if ".identity" in str(f):
                    continue
                try:
                    if f.suffix.lower() == ".pdf":
                        text = _read_pdf_text(f)
                        priority, domain = "support", ""
                    else:
                        text = f.read_text(encoding="utf-8", errors="replace")
                        priority, domain = _parse_knowledge_front_matter(text)
                        if text.strip().startswith("---"):
                            end = text.find("\n---", 3)
                            text = text[end + 4:].strip() if end >= 0 else text
                    for i, part in enumerate(_chunk_text(text, max_chars=600)):
                        part = (part or "").strip()
                        if not part:
                            continue
                        source = str(f.relative_to(knowledge_dir)).replace("\\", "/")
                        chunk_id = f"{source}_{i}"
                        content_hash = hashlib.sha1(part.encode("utf-8", errors="ignore")).hexdigest()
                        meta = {
                            "priority": priority,
                            "domain": domain or "general",
                            "source": source,
                            "chunk_index": i,
                            "content_hash": content_hash,
                        }
                        chunks.append((chunk_id, part, meta))
                except Exception:
                    continue
        if not chunks:
            return

        new_ids = {c[0] for c in chunks}
        # Remove stale ids (deleted/renamed files or reduced chunk counts)
        stale = list(existing_ids - new_ids) if existing_ids else []
        if stale:
            try:
                coll.delete(ids=stale)
            except Exception:
                pass

        # Upsert changed/new chunks only
        upsert = [c for c in chunks if existing_hash.get(c[0]) != c[2].get("content_hash")]
        if not upsert:
            return
        ids = [c[0] for c in upsert]
        documents = [c[1] for c in upsert]
        metadatas = [c[2] for c in upsert]
        embs_list = embed_batch(documents)
        import numpy as _np
        embs = _np.array(embs_list).astype("float32")
        if hasattr(coll, "upsert"):
            coll.upsert(ids=ids, embeddings=embs.tolist(), documents=documents, metadatas=metadatas)
        else:
            try:
                coll.delete(ids=ids)
            except Exception:
                pass
            coll.add(ids=ids, embeddings=embs.tolist(), documents=documents, metadatas=metadatas)
        # Mark as up-to-date so the next request doesn't immediately reindex again.
        try:
            _knowledge_fingerprint = _knowledge_dir_fingerprint(knowledge_dir)
        except Exception:
            pass
    except Exception:
        pass


def _parse_knowledge_front_matter(text: str) -> tuple[str, str]:
    """Parse optional YAML front matter for priority and domain. Returns (priority, domain). Default priority=support."""
    priority = "support"
    domain = ""
    if not (text or "").strip().startswith("---"):
        return priority, domain
    try:
        first = (text or "").split("\n")
        if first[0].strip() != "---":
            return priority, domain
        i = 1
        while i < len(first):
            line = first[i].strip()
            if line == "---":
                break
            if ":" in line:
                key, _, val = line.partition(":")
                key, val = key.strip().lower(), val.strip().lower()
                if key == "priority" and val in ("core", "support", "flavor"):
                    priority = val
                elif key == "domain":
                    domain = val[:100]
            i += 1
    except Exception:
        pass
    return priority, domain


def _knowledge_dir_fingerprint(knowledge_dir: Path) -> str:
    """Cheap fingerprint for change detection. Excludes paths containing .identity."""
    h = hashlib.sha1()
    try:
        for ext in ("*.md", "*.txt", "*.pdf"):
            for f in sorted(knowledge_dir.rglob(ext)):
                if ".identity" in str(f):
                    continue
                try:
                    st = f.stat()
                    rel = str(f.relative_to(knowledge_dir)).replace("\\", "/")
                    h.update(rel.encode("utf-8", errors="ignore"))
                    h.update(str(int(st.st_mtime)).encode("utf-8"))
                    h.update(str(int(st.st_size)).encode("utf-8"))
                except Exception:
                    continue
    except Exception:
        pass
    return h.hexdigest()


def refresh_knowledge_if_changed(knowledge_dir: Path, min_interval_s: float = 30.0) -> bool:
    """
    Conditional refresh: if knowledge/ changed, update the Chroma knowledge index.
    - Debounced (min_interval_s)
    - Preserves existing unchanged embeddings via content_hash
    - Avoids duplicate chunks via deterministic ids
    """
    global _knowledge_fingerprint, _knowledge_last_check_ts
    now = time.time()
    if (now - _knowledge_last_check_ts) < float(min_interval_s):
        return False
    _knowledge_last_check_ts = now
    fp = _knowledge_dir_fingerprint(knowledge_dir)
    if fp and fp != _knowledge_fingerprint:
        index_knowledge_docs(knowledge_dir)
        _knowledge_fingerprint = fp
        return True
    return False


def _chunk_text(text: str, max_chars: int = 600) -> list:
    """Overlap-aware chunking via langchain-text-splitters, with plain fallback."""
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(chunk_size=max_chars, chunk_overlap=100)
        return [c for c in splitter.split_text(text) if c.strip()]
    except Exception:
        # Fallback: paragraph-aware hard split
        out = []
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            if len(para) <= max_chars:
                out.append(para)
            else:
                for i in range(0, len(para), max_chars):
                    out.append(para[i: i + max_chars])
        return out


_PRIORITY_ORDER = {"core": 0, "support": 1, "flavor": 2}


def get_knowledge_chunks(query: str, k: int = 5) -> list:
    """Return up to k text chunks from the knowledge collection most relevant to query. [] if not use_chroma.
    Retrieval priority: core > support > flavor (chunks with same relevance sorted by this)."""
    if not _use_chroma():
        return []
    try:
        coll = _get_knowledge_collection()
        if coll.count() == 0:
            return []
        n_fetch = min(max(k * 3, k), coll.count())
        qvec = embed(query)
        res = coll.query(
            query_embeddings=[qvec.astype(float).tolist()],
            n_results=n_fetch,
            include=["documents", "metadatas"],
        )
        if not res or not res.get("documents") or not res["documents"][0]:
            return []
        docs = res["documents"][0]
        metas = (res.get("metadatas") or [[]])[0] if res.get("metadatas") else []
        if not metas or len(metas) != len(docs):
            return list(docs)[:k]
        combined = [(docs[i], metas[i] if i < len(metas) else {}) for i in range(len(docs))]
        combined.sort(key=lambda x: _PRIORITY_ORDER.get((x[1].get("priority") or "support").lower(), 1))
        return [c[0] for c in combined[:k]]
    except Exception:
        return []


def get_knowledge_chunks_with_sources(query: str, k: int = 5) -> list[dict]:
    """Return up to k chunks with text and source for RAG citation. [] if not use_chroma.
    Each item: {"text": str, "source": str} (source from metadata, e.g. path relative to knowledge_dir)."""
    if not _use_chroma():
        return []
    try:
        coll = _get_knowledge_collection()
        if coll.count() == 0:
            return []
        n_fetch = min(max(k * 3, k), coll.count())
        qvec = embed(query)
        res = coll.query(
            query_embeddings=[qvec.astype(float).tolist()],
            n_results=n_fetch,
            include=["documents", "metadatas"],
        )
        if not res or not res.get("documents") or not res["documents"][0]:
            return []
        docs = res["documents"][0]
        metas = (res.get("metadatas") or [[]])[0] if res.get("metadatas") else []
        if not metas or len(metas) != len(docs):
            return [{"text": d, "source": ""} for d in docs[:k]]
        combined = [(docs[i], metas[i] if i < len(metas) else {}) for i in range(len(docs))]
        combined.sort(key=lambda x: _PRIORITY_ORDER.get((x[1].get("priority") or "support").lower(), 1))
        out = []
        for doc, meta in combined[:k]:
            source = (meta.get("source") or "").strip() or "unknown"
            out.append({"text": doc, "source": source})
        return out
    except Exception:
        return []
