"""Tool implementations — domain: memory."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {}
def save_note(content: str, tag: str = "note") -> dict:
    """
    Save a note directly to Layla's memory as a learning.
    Use this to remember facts, preferences, or observations mid-conversation.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import save_learning
        save_learning(content=content[:800], kind=tag)
        return {"ok": True, "saved": content[:100]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def search_memories(query: str, n: int = 8) -> dict:
    """
    Search Layla's own memory (learnings + semantic recall) for relevant past knowledge.
    Returns the most relevant stored memories for the given query.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.vector_store import search_memories_full
        results = search_memories_full(query, k=n, use_rerank=False)
        items = [r.get("content", "") for r in results if r.get("content")]
        return {"ok": True, "memories": items, "count": len(items)}
    except Exception as e:
        try:
            from layla.memory.db import get_recent_learnings
            rows = get_recent_learnings(n=n)
            items = [r.get("content", "") for r in rows if r.get("content")]
            return {"ok": True, "memories": items, "count": len(items), "fallback": True}
        except Exception:
            return {"ok": False, "error": str(e)}

def memory_search(query: str, n: int = 8) -> dict:
    """OpenClaw-style alias: search long-term memory and learnings (same as search_memories)."""
    return search_memories(query, n=n)

def memory_get(query: str, n: int = 5) -> dict:
    """OpenClaw-style: retrieve memory snippets by semantic query."""
    return search_memories(query, n=n)

def vector_search(query: str, collection: str = "knowledge", k: int = 8) -> dict:
    """
    Direct semantic vector search over Layla's knowledge or memory collections.
    collection: 'knowledge' | 'memories' | 'aspects'
    Returns top-k results with content + similarity score.
    This is the raw retrieval layer — use search_memories for the full RAG pipeline.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        if collection == "memories":
            from layla.memory.vector_store import search_memories_full
            results = search_memories_full(query, k=k, use_rerank=False)
            return {"ok": True, "collection": collection, "query": query, "results": results[:k], "count": len(results)}
        elif collection == "knowledge":
            from layla.memory.vector_store import get_knowledge_chunks_with_sources
            chunks = get_knowledge_chunks_with_sources(query, k=k)
            results = [{"content": c.get("text", ""), "text": c.get("text", ""), "source": c.get("source", "")} for c in chunks]
            return {"ok": True, "collection": collection, "query": query, "results": results[:k], "count": len(results)}
        else:
            from layla.memory.vector_store import search_memories_full
            results = search_memories_full(query, k=k, use_rerank=False)
            return {"ok": True, "collection": collection, "query": query, "results": results[:k], "count": len(results)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def vector_store(text: str, metadata: dict | None = None, collection: str = "memories") -> dict:
    """
    Explicitly store text into Layla's vector database.
    collection: 'memories' (default) — stored as a learning and embedded.
    metadata: optional dict of tags, source, aspect, etc.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import save_learning
        meta = metadata or {}
        kind = meta.get("kind", "tool_store")
        save_learning(content=text[:800], kind=kind)
        # Also embed into vector store
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(text[:800])
            meta_with_content = {**meta, "content": text[:800]}
            add_vector(vec, meta_with_content)
        except Exception:
            pass
        return {"ok": True, "stored": text[:100], "collection": collection, "kind": kind}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def spaced_repetition_review(limit: int = 10, interval_hours: float = 24.0) -> dict:
    """
    Get learnings due for spaced repetition review. Optionally schedule next review.
    Returns items due (next_review_at <= now or NULL). Call schedule_next_review per item to reinforce.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import get_learnings_due_for_review
        due = get_learnings_due_for_review(limit=limit)
        items = [{"id": r["id"], "content": (r.get("content") or "")[:200], "importance": r.get("importance_score")} for r in due]
        return {"ok": True, "due_count": len(items), "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def schedule_learning_review(learning_id: int, interval_hours: float = 24.0) -> dict:
    """Schedule next spaced repetition review for a learning."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import schedule_next_review
        schedule_next_review(learning_id, interval_hours)
        return {"ok": True, "learning_id": learning_id, "interval_hours": interval_hours}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def memory_stats() -> dict:
    """
    Return stats about Layla's memory: learnings count, ChromaDB docs, aspect memories, DB size.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import get_recent_learnings
        learnings = get_recent_learnings(n=9999)
        result: dict = {"ok": True, "learnings_count": len(learnings)}
        db_path = agent_dir / "layla.db"
        if db_path.exists():
            result["db_size_kb"] = round(db_path.stat().st_size / 1024, 1)
        try:
            from layla.memory.vector_store import _get_knowledge_collection
            coll = _get_knowledge_collection()
            result["knowledge_docs"] = coll.count() if coll else 0
        except Exception:
            result["knowledge_docs"] = "unavailable"
        try:
            import sqlite3 as _sql
            conn = _sql.connect(str(db_path))
            rows = conn.execute("SELECT aspect_id, COUNT(*) FROM aspect_memories GROUP BY aspect_id").fetchall()
            conn.close()
            result["aspect_memories"] = {r[0]: r[1] for r in rows}
        except Exception:
            pass
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}

def memory_elasticsearch_search(query: str, limit: int = 20) -> dict:
    """Search learnings in Elasticsearch when elasticsearch_enabled (read-only)."""
    try:
        import runtime_safety
        from services.elasticsearch_bridge import search_learnings

        return search_learnings(runtime_safety.load_config(), query, limit=limit)
    except Exception as e:
        return {"ok": False, "error": str(e), "hits": []}

def ingest_chat_export_to_knowledge(export_path: str, label: str = "") -> dict:
    """
    Ingest chat export JSON/JSONL from sandbox into repo knowledge/_ingested/chats/ for RAG.
    Export file must be under sandbox_root; output is always under knowledge/_ingested/chats/.
    """
    try:
        from services.doc_ingestion import ingest_chat_export

        return ingest_chat_export(export_path, label=label)
    except Exception as e:
        return {"ok": False, "error": str(e)}

def codex_suggest_update(workspace_root: str = "", goal_hint: str = "", recent_actions: str = "") -> dict:
    """
    Read-only suggestions for `.layla/relationship_codex.json` — does not write.
    Use goal_hint / recent_actions (e.g. tool step summary) for heuristics.
    """
    from pathlib import Path

    from layla.tools import registry as _tools_registry

    wr = (workspace_root or "").strip()
    if not wr:
        return {"ok": False, "error": "workspace_root required"}
    p = Path(wr).expanduser().resolve()
    if not p.is_dir():
        return {"ok": False, "error": "workspace_root is not a directory"}
    if not _tools_registry.inside_sandbox(p):
        return {"ok": False, "error": "workspace_root outside sandbox"}
    try:
        from services.relationship_codex import suggest_codex_updates

        return suggest_codex_updates(p, goal_hint, recent_actions)
    except Exception as e:
        return {"ok": False, "error": str(e)}

