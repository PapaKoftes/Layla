"""User Profile — Layla SQLite."""
import json
import logging
import sqlite3

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")


# ── relationship memory (companion intelligence) ────────────────────────────

def add_relationship_memory(user_event: str, embedding_id: str = "") -> None:
    """Store a meaningful interaction summary for companion context. Optionally embeds for retrieval."""
    if not (user_event or "").strip():
        return
    migrate()
    event_text = (user_event or "").strip()[:4000]
    eid = (embedding_id or "").strip()
    if not eid:
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(event_text)
            eid = add_vector(vec, {"content": event_text, "type": "relationship_memory"})
        except Exception:
            pass
    with _conn() as db:
        db.execute(
            "INSERT INTO relationship_memory (user_event, timestamp, embedding_id) VALUES (?,?,?)",
            (event_text, utcnow().isoformat(), eid),
        )
        db.commit()
    try:
        from services.personal_knowledge_graph import invalidate_personal_graph
        invalidate_personal_graph()
    except Exception:
        pass


def get_recent_relationship_memories(n: int = 5) -> list[dict]:
    """Return the n most recent relationship memories (newest first)."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT id, user_event, timestamp, embedding_id FROM relationship_memory ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── timeline events (personal timeline memory) ────────────────────────────────

TIMELINE_EVENT_TYPES = ("life_event", "project_milestone", "goal", "blocker", "conversation_summary")


def add_timeline_event(
    content: str,
    event_type: str = "life_event",
    importance: float = 0.5,
    project_id: str = "",
    embedding_id: str = "",
) -> int:
    """Store a timeline event for personal memory. event_type: life_event|project_milestone|goal|blocker|conversation_summary."""
    if not (content or "").strip():
        return -1
    migrate()
    event_type = event_type if event_type in TIMELINE_EVENT_TYPES else "life_event"
    content_text = (content or "").strip()[:4000]
    imp = max(0.0, min(1.0, float(importance)))
    eid = (embedding_id or "").strip()
    if not eid:
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(content_text)
            eid = add_vector(vec, {"content": content_text, "type": "timeline_event", "event_type": event_type})
        except Exception:
            pass
    now = utcnow().isoformat()
    with _conn() as db:
        cur = db.execute(
            """INSERT INTO timeline_events (event_type, content, timestamp, importance, embedding_id, project_id, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (event_type, content_text, now, imp, eid, (project_id or "").strip(), now),
        )
        db.commit()
        return cur.lastrowid or -1


def get_recent_timeline_events(n: int = 10, min_importance: float = 0.0) -> list[dict]:
    """Return the n most recent timeline events (newest first), optionally filtered by importance."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            """SELECT id, event_type, content, timestamp, importance, project_id FROM timeline_events
               WHERE importance >= ? ORDER BY timestamp DESC LIMIT ?""",
            (min_importance, n),
        ).fetchall()
    return [dict(r) for r in rows]


# ── user identity (long-term companion context) ───────────────────────────────

USER_IDENTITY_KEYS = ("verbosity", "humor_tolerance", "formality", "response_length", "life_narrative_summary")


def get_user_identity(key: str) -> dict | None:
    """Return user identity snapshot for a key. Keys: verbosity, humor_tolerance, formality, response_length, life_narrative_summary."""
    if not (key or "").strip():
        return None
    migrate()
    with _conn() as db:
        row = db.execute("SELECT key, snapshot, updated_at FROM user_identity WHERE key=?", (key.strip(),)).fetchone()
    return dict(row) if row else None


def get_all_user_identity() -> dict[str, str]:
    """Return all user identity key-value pairs for companion context."""
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT key, snapshot FROM user_identity").fetchall()
    return {r["key"]: (r["snapshot"] or "").strip() for r in rows if r.get("key")}


def set_user_identity(key: str, snapshot: str) -> None:
    """Set user identity snapshot. Keys: verbosity, humor_tolerance, formality, response_length, life_narrative_summary."""
    if not (key or "").strip():
        return
    migrate()
    now = utcnow().isoformat()
    key = key.strip()
    snapshot = (snapshot or "").strip()[:4000]
    with _conn() as db:
        db.execute(
            """INSERT INTO user_identity (key, snapshot, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET snapshot=excluded.snapshot, updated_at=excluded.updated_at""",
            (key, snapshot, now),
        )
        db.commit()


# ── episodes (episodic memory) ──────────────────────────────────────────────

def create_episode(summary: str = "") -> str:
    """Create a new episode. Returns episode_id."""
    import uuid
    migrate()
    now = utcnow().isoformat()
    eid = str(uuid.uuid4())[:16]
    with _conn() as db:
        db.execute(
            "INSERT INTO episodes (id, summary, started_at, ended_at, created_at) VALUES (?,?,?,?,?)",
            (eid, (summary or "")[:500], now, None, now),
        )
        db.commit()
    return eid


def add_episode_event(episode_id: str, event_type: str, event_id: str = "", source_table: str = "") -> None:
    """Link an event to an episode."""
    if not episode_id:
        return
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "INSERT INTO episode_events (episode_id, event_type, event_id, source_table, created_at) VALUES (?,?,?,?,?)",
            (episode_id, event_type or "unknown", (event_id or "")[:64], (source_table or "")[:32], now),
        )
        db.commit()


def get_recent_episodes(n: int = 5) -> list[dict]:
    """Return the n most recent episodes."""
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT id, summary, started_at, ended_at FROM episodes ORDER BY started_at DESC LIMIT ?", (n,)).fetchall()
    return [dict(r) for r in rows]


# ── tool outcomes (tool reliability learning) ─────────────────────────────────

def record_tool_outcome(tool_name: str, success: bool, context: str = "", latency_ms: float = 0, quality_score: float = 0.5) -> None:
    """Record a tool outcome for reliability learning."""
    if not (tool_name or "").strip():
        return
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at) VALUES (?,?,?,?,?,?)""",
            (tool_name.strip(), (context or "")[:500], 1 if success else 0, max(0, float(latency_ms)), max(0, min(1, float(quality_score))), now),
        )
        db.commit()
    # Layla v3: maturity XP for successful tool usage (best-effort; never raise).
    if success:
        try:
            from services.maturity_engine import award_xp

            award_xp(5, reason=f"tool_success:{tool_name.strip()[:60]}")
        except Exception:
            pass


def get_tool_reliability(tool_name: str | None = None, n: int = 100) -> dict[str, dict]:
    """Return reliability stats per tool: {tool_name: {success_rate, avg_latency, avg_quality, count}}."""
    migrate()
    with _conn() as db:
        if tool_name:
            rows = db.execute(
                """SELECT tool_name, AVG(success) as success_rate, AVG(latency_ms) as avg_latency, AVG(quality_score) as avg_quality, COUNT(*) as count
                   FROM tool_outcomes WHERE tool_name=? GROUP BY tool_name""",
                (tool_name,),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT tool_name, AVG(success) as success_rate, AVG(latency_ms) as avg_latency, AVG(quality_score) as avg_quality, COUNT(*) as count
                   FROM tool_outcomes GROUP BY tool_name""",
                (),
            ).fetchall()
    result = {}
    for r in rows:
        name = r["tool_name"]
        result[name] = {
            "success_rate": float(r["success_rate"] or 0),
            "avg_latency": float(r["avg_latency"] or 0),
            "avg_quality": float(r["avg_quality"] or 0.5),
            "count": int(r["count"] or 0),
        }
    return result


def get_recent_tool_outcome_failures(limit: int = 10) -> list[dict]:
    """Return recent tool failures: [{tool_name, context, latency_ms, created_at}]."""
    migrate()
    lim = max(1, min(50, int(limit or 10)))
    try:
        with _conn() as db:
            rows = db.execute(
                "SELECT tool_name, context, latency_ms, created_at FROM tool_outcomes WHERE success=0 ORDER BY created_at DESC LIMIT ?",
                (lim,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── goals (goal engine) ─────────────────────────────────────────────────────

def add_goal(title: str, description: str = "", project_id: str = "") -> str:
    """Add a long-term goal. Returns goal_id."""
    import uuid
    migrate()
    now = utcnow().isoformat()
    gid = str(uuid.uuid4())[:16]
    with _conn() as db:
        db.execute(
            "INSERT INTO goals (id, title, description, status, project_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (gid, (title or "")[:200], (description or "")[:1000], "active", (project_id or "").strip(), now, now),
        )
        db.commit()
    return gid


def add_goal_progress(goal_id: str, note: str = "", progress_pct: float = 0) -> None:
    """Record progress on a goal."""
    if not goal_id:
        return
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "INSERT INTO goal_progress (goal_id, note, progress_pct, created_at) VALUES (?,?,?,?)",
            (goal_id, (note or "")[:500], max(0, min(100, float(progress_pct))), now),
        )
        db.execute("UPDATE goals SET updated_at=? WHERE id=?", (now, goal_id))
        db.commit()


def get_active_goals(project_id: str = "") -> list[dict]:
    """Return active goals, optionally filtered by project."""
    migrate()
    with _conn() as db:
        if project_id:
            rows = db.execute("SELECT * FROM goals WHERE status='active' AND (project_id=? OR project_id='') ORDER BY updated_at DESC", (project_id,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM goals WHERE status='active' ORDER BY updated_at DESC LIMIT 20").fetchall()
    return [dict(r) for r in rows]


# ── aspect memories ────────────────────────────────────────────────────────

def save_aspect_memory(aspect_id: str, content: str) -> None:
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO aspect_memories (aspect_id, content, created_at) VALUES (?,?,?)",
            (aspect_id, content, utcnow().isoformat()),
        )
        db.commit()


def get_aspect_memories(aspect_id: str, n: int = 10) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM aspect_memories WHERE aspect_id=? ORDER BY id DESC LIMIT ?",
            (aspect_id, n),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── earned titles ──────────────────────────────────────────────────────────

def save_earned_title(aspect_id: str, title: str) -> None:
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO earned_titles (aspect_id, title, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(aspect_id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at",
            (aspect_id, title, utcnow().isoformat()),
        )
        db.commit()


def get_earned_title(aspect_id: str) -> str | None:
    migrate()
    with _conn() as db:
        row = db.execute("SELECT title FROM earned_titles WHERE aspect_id=?", (aspect_id,)).fetchone()
    return row["title"] if row else None


