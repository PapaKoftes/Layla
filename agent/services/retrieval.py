"""
Unified retrieval: learnings (vector/BM25), documents, knowledge graph.
Merge results into a scored pool. Formula: vector*0.5 + bm25*0.3 + graph*0.2 + confidence*0.1.
Return top 6. Cached 60s. Chroma-disabled path supported.
"""
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
TOP_K = 6
W_VECTOR, W_BM25, W_GRAPH, W_CONFIDENCE = 0.5, 0.3, 0.2, 0.1
MAX_RETRIEVED_CHARS = 2000


def retrieve_learnings(query: str, k: int = TOP_K) -> list[dict]:
    """Search vector memory (Chroma if enabled) and BM25. Returns top k items."""
    results = []
    try:
        cfg = __import__("runtime_safety", fromlist=[None]).load_config()
        if cfg.get("use_chroma"):
            from layla.memory.vector_store import search_memories_full
            results = search_memories_full(query, k=k, use_rerank=False)
        if not results:
            from layla.memory.db import search_learnings_fts
            results = search_learnings_fts(query, n=k)
    except Exception:
        pass
    return results[:k]


def retrieve_documents(query: str, k: int = TOP_K) -> list[dict]:
    """BM25 / Chroma search over knowledge docs. Returns doc excerpts."""
    results = []
    try:
        cfg = __import__("runtime_safety", fromlist=[None]).load_config()
        if cfg.get("use_chroma"):
            from layla.memory.vector_store import (
                get_knowledge_chunks_with_sources,
                refresh_knowledge_if_changed,
            )
            try:
                refresh_knowledge_if_changed(REPO_ROOT / "knowledge")
            except Exception:
                pass
            chunks = get_knowledge_chunks_with_sources(query, k=k)
            for c in chunks:
                text = c.get("text", "")
                src = c.get("source", "")
                if text:
                    results.append({"text": text[:400], "source": src})
    except Exception:
        pass
    return results[:k]


def retrieve_graph_context(query: str, k: int = TOP_K) -> list[dict]:
    """Query knowledge graph for related nodes. Returns node labels and relations."""
    results = []
    try:
        from layla.memory.memory_graph import get_recent_nodes, get_neighbors
        goal_words = set(w.lower() for w in query.split() if len(w) > 2)
        recent = get_recent_nodes(n=30)
        for n in recent:
            label = (n.get("label") or "")
            if not label:
                continue
            if any(w in label.lower() for w in goal_words):
                results.append({"label": label, "type": "graph_node"})
            if len(results) >= k:
                break
        if len(results) < k:
            for n in recent[-5:]:
                if n.get("label"):
                    results.append({"label": n["label"], "type": "graph_node"})
                if len(results) >= k:
                    break
    except Exception:
        pass
    return results[:k]


def _build_retrieved_context_impl(query: str, k: int) -> str:
    """Inner implementation (called with cache when enabled). Combined output capped at MAX_RETRIEVED_CHARS."""
    learnings = retrieve_learnings(query, k=k)
    docs = retrieve_documents(query, k=k)
    graph = retrieve_graph_context(query, k=k)
    lines = []
    remaining = MAX_RETRIEVED_CHARS - len("Relevant knowledge:\n")
    for r in learnings:
        content = (r.get("content") or r.get("text") or "")[:300].strip()
        kind = (r.get("type") or r.get("learning_type") or "fact")
        if content and remaining > 40:
            line = f"* {kind}: {content}"
            if len(line) <= remaining:
                lines.append(line)
                remaining -= len(line) + 1
            else:
                lines.append(line[:remaining].rsplit(" ", 1)[0])
                break
    for d in docs:
        if remaining <= 40:
            break
        text = (d.get("text") or "")[:200].strip()
        src = d.get("source", "")
        if text:
            line = f"* doc excerpt ({src}): {text}"
            if len(line) <= remaining:
                lines.append(line)
                remaining -= len(line) + 1
            else:
                lines.append(line[:remaining].rsplit(" ", 1)[0])
                break
    for g in graph:
        if remaining <= 40:
            break
        label = (g.get("label") or "").strip()
        if label:
            line = f"* graph relation: {label}"
            if len(line) <= remaining:
                lines.append(line)
                remaining -= len(line) + 1
            else:
                break
    if not lines:
        return ""
    return "Relevant knowledge:\n" + "\n".join(lines)


def build_retrieved_context(query: str, k: int = TOP_K) -> str:
    """
    Merge learnings, documents, and graph into one block. Cached 60s.
    Total injected context capped at MAX_RETRIEVED_CHARS to avoid prompt overflow.
    """
    try:
        from services.retrieval_cache import cached_retrieve
        result = cached_retrieve(query, k, _build_retrieved_context_impl)
    except Exception:
        result = _build_retrieved_context_impl(query, k)
    if len(result) > MAX_RETRIEVED_CHARS:
        result = result[:MAX_RETRIEVED_CHARS].rsplit("\n", 1)[0] + "\n"
    return result
