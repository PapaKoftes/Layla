"""
Vector store for semantic search over learnings.
Supports FAISS (default) or ChromaDB (when use_chroma=True in config).
Embedding model: all-MiniLM-L6-v2 (dim=384) via sentence-transformers.
"""
import json
import uuid
import numpy as np
import hashlib
import time
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent
INDEX_PATH = MEMORY_DIR / "vector.index"
META_PATH = MEMORY_DIR / "vector_meta.json"
CHROMA_PATH = MEMORY_DIR / "chroma_db"

DIM = 384  # all-MiniLM-L6-v2 output dimension

_embedder = None
_chroma_collection = None
_knowledge_fingerprint: str = ""
_knowledge_last_check_ts: float = 0.0


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _use_chroma() -> bool:
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        import sys
        if str(agent_dir) not in sys.path:
            sys.path.insert(0, str(agent_dir))
        import runtime_safety
        return bool(runtime_safety.load_config().get("use_chroma", False))
    except Exception:
        return False


def _get_chroma_collection():
    global _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    _chroma_collection = client.get_or_create_collection(
        name="learnings",
        metadata={"dimension": DIM},
    )
    return _chroma_collection


# ─── FAISS backend ───────────────────────────────────────────────────────────

def _get_index():
    import faiss
    if INDEX_PATH.exists():
        return faiss.read_index(str(INDEX_PATH))
    return faiss.IndexFlatL2(DIM)


def _save_index(index) -> None:
    import faiss
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))


def _load_meta() -> list:
    if not META_PATH.exists():
        return []
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_meta(meta: list) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ─── Public API ─────────────────────────────────────────────────────────────

def embed(text: str) -> np.ndarray:
    """Return a float32 (384,) embedding for a text string."""
    model = _get_embedder()
    vec = model.encode([text], convert_to_numpy=True)[0]
    return vec.astype("float32")


def add_vector(vec: np.ndarray, metadata: dict) -> None:
    """Add a vector + metadata. When use_chroma: write to both Chroma and FAISS (RAG layer)."""
    if _use_chroma():
        try:
            coll = _get_chroma_collection()
            uid = str(uuid.uuid4())
            meta_flat = {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in metadata.items()}
            coll.add(ids=[uid], embeddings=[vec.astype(float).tolist()], metadatas=[meta_flat])
        except Exception:
            pass
        # Also write to FAISS so both stores stay populated for merged retrieval
        try:
            index = _get_index()
            index.add(np.array([vec]).astype("float32"))
            _save_index(index)
            meta = _load_meta()
            meta.append(metadata)
            _save_meta(meta)
        except Exception:
            pass
        return
    try:
        index = _get_index()
        index.add(np.array([vec]).astype("float32"))
        _save_index(index)
        meta = _load_meta()
        meta.append(metadata)
        _save_meta(meta)
    except Exception:
        pass


def _get_knowledge_collection():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_or_create_collection(name="knowledge", metadata={})


def _content_key(m: dict) -> str:
    """Normalized content for dedupe."""
    c = (m.get("content") or "").strip()[:500]
    return c


def search_similar(query_vec: np.ndarray, k: int = 5) -> list:
    """Return up to k metadata dicts. When use_chroma: merge results from Chroma and FAISS (RAG layer)."""
    seen = set()
    merged = []

    if _use_chroma():
        try:
            coll = _get_chroma_collection()
            if coll.count() > 0:
                n = min(k, coll.count())
                res = coll.query(
                    query_embeddings=[query_vec.astype(float).tolist()],
                    n_results=n,
                    include=["metadatas"],
                )
                if res and res.get("metadatas") and res["metadatas"][0]:
                    for m in res["metadatas"][0]:
                        key = _content_key(m)
                        if key and key not in seen:
                            seen.add(key)
                            merged.append(m)
        except Exception:
            pass
        # Layer FAISS on top: add results that aren't duplicates
        try:
            index = _get_index()
            if index.ntotal > 0:
                n = min(k, index.ntotal)
                _, indices = index.search(np.array([query_vec]).astype("float32"), n)
                meta = _load_meta()
                for idx in indices[0]:
                    if 0 <= idx < len(meta) and len(merged) >= k:
                        break
                    if 0 <= idx < len(meta):
                        m = meta[idx]
                        key = _content_key(m)
                        if key and key not in seen:
                            seen.add(key)
                            merged.append(m)
        except Exception:
            pass
        return merged[:k]
    try:
        index = _get_index()
        if index.ntotal == 0:
            return []
        k_use = min(k, index.ntotal)
        _, indices = index.search(np.array([query_vec]).astype("float32"), k_use)
        meta = _load_meta()
        for idx in indices[0]:
            if 0 <= idx < len(meta):
                merged.append(meta[idx])
        return merged
    except Exception:
        return []


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
        embs = _get_embedder().encode(documents, convert_to_numpy=True).astype("float32")
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
    out = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            out.append(para)
        else:
            for i in range(0, len(para), max_chars):
                out.append(para[i : i + max_chars])
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
