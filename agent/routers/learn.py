"""Learn, schedule, and memory search endpoints. Mounted under main agent router."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from shared_state import get_touch_activity

logger = logging.getLogger("layla")
router = APIRouter(tags=["agent"])


@router.get("/memories")
def search_memories(q: str = "", n: int = 8, aspect_id: str = ""):
    """Search Layla's memories. q=query, n=max results."""
    get_touch_activity()()
    if not (q or "").strip():
        return JSONResponse({"ok": True, "memories": [], "count": 0})
    try:
        from layla.memory.vector_store import search_memories_full

        results = search_memories_full(q.strip(), k=min(n, 20), use_rerank=False)
        items = [r.get("content", "") for r in results if r.get("content")]
        return JSONResponse({"ok": True, "memories": items, "count": len(items)})
    except Exception as e:
        logger.warning("search_memories failed: %s", e)
        try:
            from layla.memory.db import search_learnings_fts
            rows = search_learnings_fts(q.strip(), n=min(n, 20), aspect_id=aspect_id or None)
            items = [r.get("content", "") for r in rows if r.get("content")]
            return JSONResponse({"ok": True, "memories": items, "count": len(items)})
        except Exception as e2:
            logger.warning("search_learnings_fts fallback failed: %s", e2)
            return JSONResponse({"ok": False, "error": str(e2), "memories": [], "count": 0})


@router.post("/schedule")
def schedule(req: dict):
    """Schedule a tool to run in background. tool_name, args, delay_seconds, cron_expr."""
    get_touch_activity()()
    r = req or {}
    tool_name = (r.get("tool_name") or "").strip()
    if not tool_name:
        return JSONResponse({"ok": False, "error": "tool_name required"})
    try:
        from layla.tools.registry import TOOLS, schedule_task
        if tool_name not in TOOLS:
            return JSONResponse({"ok": False, "error": f"Unknown tool: {tool_name}"})
        raw_delay = float(r.get("delay_seconds") or 0)
        delay_seconds = max(0.0, min(86400.0, raw_delay)) if not (raw_delay != raw_delay) else 0.0  # clamp 0-24h, reject NaN
        result = schedule_task(
            tool_name=tool_name,
            args=r.get("args") or {},
            delay_seconds=delay_seconds,
            cron_expr=(r.get("cron_expr") or "").strip(),
        )
        return JSONResponse(result)
    except Exception as e:
        logger.exception("schedule failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/learn/")
def learn(req: dict):
    get_touch_activity()()
    content = (req or {}).get("content", "").strip()
    kind = (req or {}).get("type", "fact") or "fact"
    tags = str((req or {}).get("tags") or "").strip()[:500]
    aspect_id = str((req or {}).get("aspect_id") or "").strip()[:64]
    if not content:
        return JSONResponse({"ok": False, "error": "No content"})
    try:
        embedding_id = ""
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(content)
            meta = {"content": content, "type": kind}
            if tags:
                meta["tags"] = tags
            if aspect_id:
                meta["aspect_id"] = aspect_id
            embedding_id = add_vector(vec, meta)
        except Exception as e:
            logger.warning("vector_store add_vector failed: %s", e)
        from layla.memory.db import save_learning
        save_learning(content=content, kind=kind, embedding_id=embedding_id, tags=tags, aspect_id=aspect_id)
        try:
            from layla.memory.memory_graph import add_node
            add_node(label=content[:80], metadata={"type": kind, "content": content})
        except Exception as e:
            logger.warning("memory_graph add_node failed: %s", e)
        return JSONResponse({"ok": True, "message": "Saved."})
    except Exception as e:
        logger.exception("learn failed")
        return JSONResponse({"ok": False, "error": str(e)})
