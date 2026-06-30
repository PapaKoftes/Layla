"""Learn, schedule, memory search, verification, and growth endpoints.

Mounted under main agent router.
"""
import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from schemas.requests import LearnRequest, ScheduleRequest
from shared_state import get_touch_activity

logger = logging.getLogger("layla")
router = APIRouter(tags=["agent"])


# ── Verification request models ──────────────────────────────────────────

class VerifyAnswerRequest(BaseModel):
    fact_id: str
    confirmed: bool
    correction: str = ""


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
def schedule(req: ScheduleRequest):
    """Schedule a tool to run in background. tool_name, args, delay_seconds, cron_expr."""
    get_touch_activity()()
    tool_name = req.tool_name
    try:
        from layla.tools.registry import TOOLS, schedule_task
        if tool_name not in TOOLS:
            return JSONResponse({"ok": False, "error": f"Unknown tool: {tool_name}"}, status_code=400)
        result = schedule_task(
            tool_name=tool_name,
            args=req.args or {},
            delay_seconds=req.delay_seconds,
            cron_expr=(req.cron_expr or "").strip(),
        )
        return JSONResponse(result)
    except Exception as e:
        logger.exception("schedule failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/learn/")
def learn(req: LearnRequest):
    get_touch_activity()()
    content = req.content.strip()
    kind = req.type or "fact"
    tags = (req.tags or "").strip()
    aspect_id = (req.aspect_id or "").strip()
    if not content:
        return JSONResponse({"ok": False, "error": "No content"}, status_code=400)
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
        from services.memory.memory_router import save_learning  # canonical write path
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


# ── Fact correction endpoint (Gap 6) ────────────────────────────────────


class FactCorrectionRequest(BaseModel):
    """Request to correct a learned fact."""
    query: str = Field(..., description="The incorrect fact text or search query")
    correction: str = Field(..., description="The corrected fact content")
    aspect_id: str = ""


@router.post("/learn/correct")
def correct_fact(req: FactCorrectionRequest):
    """Correct a learned fact: find the closest match, update it, re-embed."""
    get_touch_activity()()
    query = (req.query or "").strip()
    correction = (req.correction or "").strip()
    if not query or not correction:
        return JSONResponse({"ok": False, "error": "query and correction required"}, status_code=400)

    try:
        from layla.memory.db_connection import _conn

        # 1. Find the closest matching learning by FTS or LIKE
        matched_id = None
        old_content = None
        with _conn() as db:
            # Try exact match first
            row = db.execute(
                "SELECT id, content FROM learnings WHERE content = ? LIMIT 1", (query,)
            ).fetchone()
            if row:
                matched_id = row[0] if not isinstance(row, dict) else row["id"]
                old_content = row[1] if not isinstance(row, dict) else row["content"]
            else:
                # Try FTS
                try:
                    from layla.memory.db import search_learnings_fts
                    results = search_learnings_fts(query, n=1, aspect_id=req.aspect_id or None)
                    if results:
                        r = results[0]
                        matched_id = r.get("id") or r.get("rowid")
                        old_content = r.get("content", "")
                except Exception:
                    pass

                # Fallback: LIKE search
                if not matched_id:
                    row = db.execute(
                        "SELECT id, content FROM learnings WHERE content LIKE ? LIMIT 1",
                        (f"%{query[:60]}%",),
                    ).fetchone()
                    if row:
                        matched_id = row[0] if not isinstance(row, dict) else row["id"]
                        old_content = row[1] if not isinstance(row, dict) else row["content"]

        if not matched_id:
            return JSONResponse({"ok": False, "error": "No matching fact found", "query": query})

        # 2. Update the learning content
        with _conn() as db:
            db.execute(
                "UPDATE learnings SET content = ?, confidence = 1.0, updated_at = datetime('now') WHERE id = ?",
                (correction, matched_id),
            )

        # 3. Re-embed in vector store
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(correction)
            meta = {"content": correction, "type": "fact", "corrected": True}
            if req.aspect_id:
                meta["aspect_id"] = req.aspect_id
            add_vector(vec, meta)
        except Exception as ve:
            logger.warning("re-embed after correction failed: %s", ve)

        # 4. Record the correction event for maturity tracking
        try:
            from services.personality.maturity_engine import get_maturity_engine
            me = get_maturity_engine()
            me.record_relationship_event("correction")
        except Exception:
            pass

        return JSONResponse({
            "ok": True,
            "message": "Fact corrected",
            "old_content": old_content,
            "new_content": correction,
            "learning_id": str(matched_id),
        })
    except Exception as e:
        logger.exception("fact correction failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── Verification endpoints (Phase 5B) ───────────────────────────────────

@router.get("/verify/next")
def verify_next():
    """Get the next fact awaiting user verification."""
    try:
        from services.planning.verification_queue import get_next_verification
        fact = get_next_verification()
        if fact is None:
            return JSONResponse({"ok": True, "fact": None, "message": "No pending verifications"})
        return JSONResponse({"ok": True, "fact": fact})
    except Exception as e:
        logger.warning("verify/next failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/verify/answer")
def verify_answer(req: VerifyAnswerRequest):
    """Record the user's answer for a verification prompt."""
    try:
        from services.planning.verification_queue import get_verification_queue
        result = get_verification_queue().answer(req.fact_id, req.confirmed, req.correction)
        return JSONResponse(result)
    except Exception as e:
        logger.warning("verify/answer failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/verify/stats")
def verify_stats():
    """Get verification queue statistics."""
    try:
        from services.planning.verification_queue import get_verification_queue
        stats = get_verification_queue().get_stats()
        return JSONResponse({"ok": True, **stats})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ── Growth dashboard endpoint (Phase 5D) ────────────────────────────────

@router.get("/api/growth/stats")
def growth_stats():
    """Get combined growth statistics for the dashboard."""
    result: dict = {"ok": True}

    # Total facts / learnings
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            total = db.execute("SELECT COUNT(*) FROM learnings").fetchone()
            result["total_facts"] = total[0] if total else 0

            # High-confidence facts
            confirmed = db.execute(
                "SELECT COUNT(*) FROM learnings WHERE confidence >= 0.9"
            ).fetchone()
            result["high_confidence_facts"] = confirmed[0] if confirmed else 0

            # Learning types breakdown
            types = db.execute(
                "SELECT type, COUNT(*) as cnt FROM learnings GROUP BY type ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
            result["learning_types"] = {
                (r["type"] if isinstance(r, dict) else r[0]): (r["cnt"] if isinstance(r, dict) else r[1])
                for r in types
            }

            # Recent learnings (last 7 days)
            recent = db.execute(
                "SELECT COUNT(*) FROM learnings WHERE created_at > datetime('now', '-7 days')"
            ).fetchone()
            result["learnings_last_7_days"] = recent[0] if recent else 0

            # Learning velocity (last 30 days, per week)
            velocity = db.execute("""
                SELECT strftime('%Y-W%W', created_at) as week, COUNT(*) as cnt
                FROM learnings
                WHERE created_at > datetime('now', '-30 days')
                GROUP BY week
                ORDER BY week
            """).fetchall()
            result["velocity_by_week"] = {
                (r["week"] if isinstance(r, dict) else r[0]): (r["cnt"] if isinstance(r, dict) else r[1])
                for r in velocity
            }
    except Exception as e:
        result["facts_error"] = str(e)

    # Verification stats
    try:
        from services.planning.verification_queue import get_verification_queue
        result["verification"] = get_verification_queue().get_stats()
    except Exception:
        result["verification"] = {}

    # Capability levels
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            caps = db.execute(
                """SELECT cd.name, c.level, c.confidence, c.trend, c.practice_count
                   FROM capabilities c
                   JOIN capability_domains cd ON c.domain_id = cd.id
                   ORDER BY c.level DESC"""
            ).fetchall()
            result["capabilities"] = [
                {
                    "name": (r["name"] if isinstance(r, dict) else r[0]),
                    "level": (r["level"] if isinstance(r, dict) else r[1]),
                    "confidence": (r["confidence"] if isinstance(r, dict) else r[2]),
                    "trend": (r["trend"] if isinstance(r, dict) else r[3]),
                    "practice_count": (r["practice_count"] if isinstance(r, dict) else r[4]),
                }
                for r in caps
            ]
    except Exception:
        result["capabilities"] = []

    # Knowledge watcher stats
    try:
        from services.memory.knowledge_watcher import get_knowledge_watcher
        result["knowledge_watcher"] = get_knowledge_watcher().get_stats()
    except Exception:
        result["knowledge_watcher"] = {}

    # Study plans
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            plans = db.execute(
                "SELECT COUNT(*) FROM study_plans WHERE status = 'active'"
            ).fetchone()
            result["active_study_plans"] = plans[0] if plans else 0
    except Exception:
        result["active_study_plans"] = 0

    return JSONResponse(result)
