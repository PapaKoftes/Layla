"""Operator journal — durable entries for continuity."""

from __future__ import annotations

import logging
from typing import Any

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")


def _norm_tags(tags: str | list[str]) -> str:
    if tags is None:
        return ""
    if isinstance(tags, str):
        parts = [p.strip().lower() for p in tags.replace(";", ",").split(",")]
    else:
        parts = [str(p).strip().lower() for p in tags]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if not p:
            continue
        safe = "".join(ch for ch in p if ch.isalnum() or ch in ("_", "-", "/"))[:32].strip()
        if not safe or safe in seen:
            continue
        seen.add(safe)
        out.append(safe)
    return ",".join(out)


def add_journal_entry(
    entry_type: str,
    content: str,
    *,
    tags: str | list[str] = "",
    project_id: str = "",
    aspect_id: str = "",
    conversation_id: str = "",
) -> dict[str, Any]:
    migrate()
    et = (entry_type or "note").strip()[:40] or "note"
    c = (content or "").strip()
    if not c:
        return {"ok": False, "error": "content required"}
    now = utcnow().isoformat()
    tg = _norm_tags(tags)
    with _conn() as db:
        cur = db.execute(
            """
            INSERT INTO operator_journal (created_at, entry_type, content, tags, project_id, aspect_id, conversation_id)
            VALUES (?,?,?,?,?,?,?)
            """,
            (now, et, c[:20000], tg, (project_id or "").strip(), (aspect_id or "").strip(), (conversation_id or "").strip()),
        )
        db.commit()
        rid = int(cur.lastrowid or 0)
        row = db.execute("SELECT * FROM operator_journal WHERE id=?", (rid,)).fetchone()
    return {"ok": True, "entry": dict(row) if row else {"id": rid}}


def list_journal_entries(limit: int = 50, *, day: str = "") -> list[dict[str, Any]]:
    migrate()
    lim = max(1, min(int(limit or 50), 500))
    d = (day or "").strip()
    with _conn() as db:
        if d:
            # match YYYY-MM-DD prefix
            rows = db.execute(
                "SELECT * FROM operator_journal WHERE created_at LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"{d}%", lim),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM operator_journal ORDER BY created_at DESC LIMIT ?",
                (lim,),
            ).fetchall()
    return [dict(r) for r in rows]

