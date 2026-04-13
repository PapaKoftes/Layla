"""Conversations — Layla SQLite."""
import json
import logging
import sqlite3

from layla.time_utils import utcnow

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")


# ── conversation summaries (context overflow prevention) ────────────────────

def add_conversation_summary(summary: str) -> None:
    """Persist a conversation summary for long-term context retention. Stores embedding for retrieval."""
    if not (summary or "").strip():
        return
    migrate()
    summary_text = summary.strip()[:8000]
    embedding_id = ""
    try:
        from layla.memory.vector_store import add_vector, embed
        vec = embed(summary_text)
        embedding_id = add_vector(vec, {"content": summary_text, "type": "conversation_summary"})
    except Exception:
        pass
    with _conn() as db:
        db.execute(
            "INSERT INTO conversation_summaries (summary, created_at, embedding_id) VALUES (?,?,?)",
            (summary_text, utcnow().isoformat(), embedding_id),
        )
        db.commit()


def get_recent_conversation_summaries(n: int = 5) -> list[dict]:
    """Return the n most recent conversation summaries (newest first)."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT id, summary, created_at, embedding_id FROM conversation_summaries ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


def _auto_name_conversation(first_user_message: str) -> str:
    t = (first_user_message or "").strip().replace("\n", " ")
    if not t:
        return "New chat"
    if len(t) <= 40:
        return t
    return t[:40].rstrip() + "..."


def create_conversation(conversation_id: str, title: str = "", aspect_id: str = "") -> dict:
    migrate()
    now = utcnow().isoformat()
    cid = (conversation_id or "").strip()
    if not cid:
        import uuid

        cid = str(uuid.uuid4())
    with _conn() as db:
        db.execute(
            """INSERT OR IGNORE INTO conversations
               (id, title, aspect_id, dominant_aspect, created_at, updated_at, message_count)
               VALUES (?,?,?,?,?,?,0)""",
            (cid, (title or "").strip(), (aspect_id or "").strip(), (aspect_id or "").strip(), now, now),
        )
        db.commit()
        row = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else {"id": cid}


def get_conversation(conversation_id: str) -> dict | None:
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM conversations WHERE id=?", ((conversation_id or "").strip(),)).fetchone()
    return dict(row) if row else None


def list_conversations(limit: int = 200) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
    return [dict(r) for r in rows]


def rename_conversation(conversation_id: str, title: str) -> bool:
    migrate()
    with _conn() as db:
        cur = db.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
            ((title or "").strip()[:120], utcnow().isoformat(), (conversation_id or "").strip()),
        )
        db.commit()
        return cur.rowcount > 0


def delete_conversation(conversation_id: str) -> bool:
    migrate()
    cid = (conversation_id or "").strip()
    if not cid:
        return False
    with _conn() as db:
        db.execute("DELETE FROM conversation_messages WHERE conversation_id=?", (cid,))
        cur = db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        db.commit()
        return cur.rowcount > 0


def append_conversation_message(
    conversation_id: str,
    role: str,
    content: str,
    aspect_id: str = "",
    token_count: int = 0,
) -> str:
    import uuid

    migrate()
    cid = (conversation_id or "").strip()
    if not cid:
        create = create_conversation("", "")
        cid = create["id"]
    msg_id = str(uuid.uuid4())
    now = utcnow().isoformat()
    safe_content = (content or "").strip()
    safe_role = (role or "assistant").strip()
    with _conn() as db:
        db.execute(
            """INSERT INTO conversation_messages
               (id, conversation_id, role, content, aspect_id, created_at, token_count)
               VALUES (?,?,?,?,?,?,?)""",
            (msg_id, cid, safe_role, safe_content, (aspect_id or "").strip(), now, max(0, int(token_count or 0))),
        )
        row = db.execute("SELECT title, message_count FROM conversations WHERE id=?", (cid,)).fetchone()
        title = (row["title"] or "").strip() if row else ""
        count = int(row["message_count"] or 0) if row else 0
        if safe_role == "user" and not title and count == 0:
            title = _auto_name_conversation(safe_content)
        dom = (aspect_id or "").strip()
        db.execute(
            """UPDATE conversations
               SET updated_at=?, message_count=COALESCE(message_count,0)+1,
                   title=CASE WHEN ?!='' THEN ? ELSE title END,
                   dominant_aspect=CASE WHEN ?!='' THEN ? ELSE dominant_aspect END,
                   aspect_id=CASE WHEN ?!='' THEN ? ELSE aspect_id END
               WHERE id=?""",
            (now, title, title, dom, dom, dom, dom, cid),
        )
        db.commit()
    return msg_id


def get_conversation_messages(conversation_id: str, limit: int = 200) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            """SELECT id, conversation_id, role, content, aspect_id, created_at, token_count
               FROM conversation_messages
               WHERE conversation_id=?
               ORDER BY created_at ASC
               LIMIT ?""",
            ((conversation_id or "").strip(), max(1, min(int(limit), 2000))),
        ).fetchall()
    return [dict(r) for r in rows]


def search_conversations(query: str, limit: int = 50) -> list[dict]:
    migrate()
    q = (query or "").strip()
    if not q:
        return list_conversations(limit=limit)
    with _conn() as db:
        rows = db.execute(
            """SELECT DISTINCT c.*
               FROM conversations c
               LEFT JOIN conversation_messages m ON m.conversation_id = c.id
               WHERE c.title LIKE ? OR m.content LIKE ?
               ORDER BY c.updated_at DESC
               LIMIT ?""",
            (f"%{q}%", f"%{q}%", max(1, min(int(limit), 500))),
        ).fetchall()
    return [dict(r) for r in rows]


