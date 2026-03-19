"""
Unified retrieval: learnings (vector/BM25), documents, knowledge graph.
Merge results into a scored pool. Formula: vector*0.5 + bm25*0.3 + graph*0.2 + confidence*0.1.
Return top 6. Cached 60s. Chroma-disabled path supported.
Runs learnings, documents, graph retrieval in parallel.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger("layla")
AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
TOP_K = 6
# Cap for merged retrieval context (prompt safety)
MAX_K = 5
W_VECTOR, W_BM25, W_GRAPH, W_CONFIDENCE = 0.5, 0.3, 0.2, 0.1
MAX_RETRIEVED_CHARS = 2000


def _word_set(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z0-9_]{2,}", (s or "").lower())}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    u = len(a | b)
    if u == 0:
        return 0.0
    return len(a & b) / u


def _retrieval_guard_config() -> tuple[int, float]:
    try:
        cfg = __import__("runtime_safety", fromlist=[None]).load_config()
        cap = max(50, int(cfg.get("max_chars_per_source", 500)))
        sim = float(cfg.get("retrieval_line_overlap_threshold", 0.7))
        sim = max(0.0, min(1.0, sim))
        return cap, sim
    except Exception:
        return 500, 0.7


def retrieve_learnings(query: str, k: int = TOP_K, *, coding_boost: bool = False) -> list[dict]:
    """Search vector memory (Chroma if enabled) and BM25. Returns top k items."""
    results = []
    try:
        cfg = __import__("runtime_safety", fromlist=[None]).load_config()
        if cfg.get("use_chroma"):
            from layla.memory.vector_store import search_memories_full
            results = search_memories_full(query, k=k, use_rerank=False, coding_boost=coding_boost)
        if not results:
            from layla.memory.db import search_learnings_fts
            results = search_learnings_fts(query, n=k)
    except Exception as e:
        logger.debug("retrieve_learnings failed: %s", e)
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
            except Exception as e:
                logger.debug("retrieve_documents refresh_knowledge failed: %s", e)
            chunks = get_knowledge_chunks_with_sources(query, k=k)
            for c in chunks:
                text = c.get("text", "")
                src = c.get("source", "")
                if text:
                    results.append({"text": text[:400], "source": src})
    except Exception as e:
        logger.debug("retrieve_documents failed: %s", e)
    return results[:k]


def retrieve_graph_context(query: str, k: int = TOP_K) -> list[dict]:
    """Query knowledge graph for related nodes. Uses graph_reasoning when available for entity extraction + expansion."""
    results = []
    try:
        from services.graph_reasoning import expand_query_via_graph
        expanded = expand_query_via_graph(query, max_hops=2, max_nodes=k)
        for n in expanded:
            label = (n.get("label") or "").strip()
            if label:
                results.append({"label": label, "type": "graph_node"})
    except Exception as e:
        logger.debug("retrieve_graph_context expand_query failed: %s", e)
    if not results:
        try:
            from layla.memory.memory_graph import get_recent_nodes
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
        except Exception as e:
            logger.debug("retrieve_graph_context get_recent_nodes failed: %s", e)
    return results[:k]


def _build_retrieved_context_impl(query: str, k: int, *, coding_boost: bool = False) -> str:
    """Inner implementation (called with cache when enabled). Combined output capped at MAX_RETRIEVED_CHARS.
    Runs learnings, documents, graph retrieval in parallel."""
    k = max(1, min(int(k), MAX_K))
    learnings, docs, graph = [], [], []
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_learn = ex.submit(retrieve_learnings, query, k, coding_boost=coding_boost)
        f_docs = ex.submit(retrieve_documents, query, k)
        f_graph = ex.submit(retrieve_graph_context, query, k)
        learnings = f_learn.result()
        docs = f_docs.result()
        graph = f_graph.result()
    lines: list[str] = []
    line_word_sets: list[set[str]] = []
    remaining = MAX_RETRIEVED_CHARS - len("Relevant knowledge:\n")
    per_cap, overlap_th = _retrieval_guard_config()

    def _append_line(line: str) -> bool:
        nonlocal remaining
        if remaining <= 40 or not line.strip():
            return False
        cap_body = per_cap
        if len(line) > cap_body:
            line = line[:cap_body].rsplit(" ", 1)[0]
        ws = _word_set(line)
        for prev_ws in line_word_sets:
            if _jaccard(ws, prev_ws) > overlap_th:
                return False
        if len(line) > remaining:
            line = line[:remaining].rsplit(" ", 1)[0]
        if not line.strip():
            return False
        lines.append(line)
        line_word_sets.append(ws)
        remaining -= len(line) + 1
        return True

    for r in learnings:
        content = (r.get("content") or r.get("text") or "").strip()
        if len(content) > per_cap:
            content = content[:per_cap].rsplit(" ", 1)[0]
        kind = (r.get("type") or r.get("learning_type") or "fact")
        if content and remaining > 40:
            line = f"* {kind}: {content}"
            if not _append_line(line):
                break
    for d in docs:
        if remaining <= 40:
            break
        text = (d.get("text") or "").strip()
        if len(text) > per_cap:
            text = text[:per_cap].rsplit(" ", 1)[0]
        src = d.get("source", "")
        if text:
            line = f"* doc excerpt ({src}): {text}"
            if not _append_line(line):
                break
    for g in graph:
        if remaining <= 40:
            break
        label = (g.get("label") or "").strip()
        if len(label) > per_cap:
            label = label[:per_cap]
        if label:
            line = f"* graph relation: {label}"
            if not _append_line(line):
                break
    if not lines:
        return ""
    return "Relevant knowledge:\n" + "\n".join(lines)


def build_retrieved_context(query: str, k: int = TOP_K, reasoning_mode: str = "light") -> str:
    """
    Merge learnings, documents, and graph into one block. Cached 60s.
    Total injected context capped at MAX_RETRIEVED_CHARS to avoid prompt overflow.
    """
    rm = (reasoning_mode or "light").strip().lower()
    if rm == "light" and len((query or "").strip()) < 20:
        return ""
    k = max(1, min(int(k), MAX_K))
    coding_boost = (reasoning_mode or "").strip().lower() == "deep"
    cache_query = f"{query}\x1e{'deep' if coding_boost else 'std'}"
    try:
        from services.retrieval_cache import cached_retrieve

        def _fetch(_q: str, kk: int) -> str:
            return _build_retrieved_context_impl(query, kk, coding_boost=coding_boost)

        result = cached_retrieve(cache_query, k, _fetch)
    except Exception as e:
        logger.debug("build_retrieved_context cache failed: %s", e)
        result = _build_retrieved_context_impl(query, k, coding_boost=coding_boost)
    if len(result) > MAX_RETRIEVED_CHARS:
        result = result[:MAX_RETRIEVED_CHARS].rsplit("\n", 1)[0] + "\n"
    return result
