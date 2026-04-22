"""
Global smart search across conversations, learnings, workspace, and knowledge (Phase 1.4).

GET /search?q=&context=all&limit=20
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("layla")

router = APIRouter(tags=["search"])


@router.get("/search")
async def global_search(
    q: str = Query("", description="Search query"),
    context: str = Query("all", description="all | conversations | learnings | workspace | knowledge"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Cross-context semantic + keyword search.

    Returns grouped results: conversations, learnings, workspace, knowledge.
    Each group has up to limit//4 results (or full limit when context is scoped).
    """
    q = (q or "").strip()
    if not q:
        return {"ok": True, "q": q, "conversations": [], "learnings": [], "workspace": [], "knowledge": []}

    ctx = (context or "all").strip().lower()
    per_group = max(4, limit // 4) if ctx == "all" else limit
    results: dict = {"ok": True, "q": q}

    # ── Conversations ────────────────────────────────────────────────────────
    conversations: list[dict] = []
    if ctx in ("all", "conversations"):
        try:
            from layla.memory.db_connection import _conn
            from layla.memory.migrations import migrate

            migrate()
            with _conn() as db:
                rows = db.execute(
                    "SELECT id, title, aspect_id, updated_at FROM conversations"
                    " WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?",
                    (f"%{q}%", per_group),
                ).fetchall()
            # FTS search is best-effort; must not discard title LIKE results on failure
            msg_rows = []
            try:
                # Escape FTS special chars by wrapping in double quotes
                _fts_q = '"' + q.replace('"', '""') + '"'
                with _conn() as db:
                    msg_rows = db.execute(
                        "SELECT DISTINCT conversation_id FROM conversation_messages_fts"
                        " WHERE conversation_messages_fts MATCH ? LIMIT ?",
                        (_fts_q, per_group),
                    ).fetchall()
            except Exception:
                pass
            seen = {str(r["id"]) for r in rows}
            for r in rows:
                conversations.append({
                    "id": r["id"],
                    "title": r["title"] or "New chat",
                    "aspect_id": r["aspect_id"] or "",
                    "updated_at": r["updated_at"] or "",
                    "match": "title",
                })
            for mr in msg_rows:
                cid = str(mr["conversation_id"] or mr[0])
                if cid in seen:
                    continue
                seen.add(cid)
                with _conn() as db:
                    meta = db.execute(
                        "SELECT id, title, updated_at FROM conversations WHERE id=?", (cid,)
                    ).fetchone()
                if meta:
                    conversations.append({
                        "id": meta["id"],
                        "title": meta["title"] or "New chat",
                        "updated_at": meta["updated_at"] or "",
                        "match": "message",
                    })
        except Exception as e:
            logger.debug("search/conversations: %s", e)
    results["conversations"] = conversations[:per_group]

    # ── Learnings ────────────────────────────────────────────────────────────
    learnings: list[dict] = []
    if ctx in ("all", "learnings"):
        try:
            from services.retrieval import retrieve_relevant_memory

            mem_rows = retrieve_relevant_memory(q, k=per_group, coding_boost=False)
            for r in mem_rows:
                learnings.append({
                    "id": r.get("id"),
                    "content": (r.get("content") or "")[:200],
                    "type": r.get("type") or "fact",
                    "score": float(r.get("score") or 0.5),
                })
        except Exception as e:
            logger.debug("search/learnings semantic: %s", e)
        # Supplement with FTS keyword hits when semantic returns few results
        if len(learnings) < per_group // 2:
            try:
                from layla.memory.db_connection import _conn
                with _conn() as db:
                    rows = db.execute(
                        "SELECT id, content, type FROM learnings_fts"
                        " WHERE learnings_fts MATCH ? LIMIT ?",
                        (q, per_group),
                    ).fetchall()
                seen_ids = {str(r.get("id")) for r in learnings if r.get("id")}
                for r in rows:
                    if str(r[0]) not in seen_ids:
                        learnings.append({"id": r[0], "content": (r[1] or "")[:200], "type": r[2] or "fact", "score": 0.6})
            except Exception:
                pass
    results["learnings"] = learnings[:per_group]

    # ── Workspace ────────────────────────────────────────────────────────────
    workspace: list[dict] = []
    if ctx in ("all", "workspace"):
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
            ws_root = (cfg.get("sandbox_root") or "").strip()
            if ws_root:
                from services.workspace_index import retrieve_code_context

                code_rows = retrieve_code_context(q, workspace_root=ws_root, k=per_group)
                for r in code_rows:
                    meta = r.get("metadata") or {}
                    workspace.append({
                        "path": meta.get("source") or meta.get("path") or "",
                        "snippet": (r.get("text") or "")[:200],
                        "score": float(r.get("score") or 0.5),
                    })
        except Exception as e:
            logger.debug("search/workspace: %s", e)
    results["workspace"] = workspace[:per_group]

    # ── Knowledge ────────────────────────────────────────────────────────────
    knowledge: list[dict] = []
    if ctx in ("all", "knowledge"):
        try:
            from services.retrieval import retrieve_documents

            k_rows = retrieve_documents(q, k=per_group)
            for r in k_rows:
                knowledge.append({
                    "source": r.get("source") or r.get("id") or "",
                    "snippet": (r.get("content") or r.get("text") or "")[:200],
                    "score": float(r.get("score") or 0.5),
                })
        except Exception as e:
            logger.debug("search/knowledge: %s", e)
    results["knowledge"] = knowledge[:per_group]

    return results
