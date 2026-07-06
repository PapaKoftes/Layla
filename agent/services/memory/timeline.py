"""Temporal memory timeline (BL-234) — navigate memories chronologically.

The `timeline_events` + `episodes`/`episode_events` tables already accrue life events,
milestones, goals and episode groupings. This adds the *read* surface to walk them in
time: a filtered/paginated timeline query, day buckets for a calendar-style view, and
episode reconstruction (an episode + the events that belong to it). ISO-8601 timestamps
mean lexical comparison is chronological, so range filters are plain string bounds.
"""
from __future__ import annotations

import logging
from typing import Any

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")


def query_timeline(
    *,
    since: str = "",
    until: str = "",
    event_type: str = "",
    project_id: str = "",
    min_importance: float = 0.0,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Timeline events in a window, newest-first, with optional type/project filters."""
    migrate()
    where = ["importance >= ?"]
    params: list[Any] = [float(min_importance)]
    if since:
        where.append("timestamp >= ?")
        params.append(since)
    if until:
        where.append("timestamp <= ?")
        params.append(until)
    if event_type:
        where.append("event_type = ?")
        params.append(event_type)
    if project_id:
        where.append("project_id = ?")
        params.append(project_id)
    clause = " AND ".join(where)
    with _conn() as db:
        total = db.execute(f"SELECT COUNT(*) FROM timeline_events WHERE {clause}", params).fetchone()[0]
        rows = db.execute(
            f"""SELECT id, event_type, content, timestamp, importance, project_id
                FROM timeline_events WHERE {clause}
                ORDER BY timestamp DESC LIMIT ? OFFSET ?""",
            (*params, int(limit), int(offset)),
        ).fetchall()
    return {"total": total, "count": len(rows), "offset": offset, "events": [dict(r) for r in rows]}


def timeline_days(*, limit_days: int = 60) -> dict[str, Any]:
    """Per-day event counts (for a calendar/heatmap), newest days first."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            """SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS n,
                      MAX(importance) AS top_importance
               FROM timeline_events GROUP BY day ORDER BY day DESC LIMIT ?""",
            (int(limit_days),),
        ).fetchall()
    return {"days": [dict(r) for r in rows]}


def list_episodes(*, limit: int = 20) -> dict[str, Any]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT id, summary, started_at, ended_at FROM episodes ORDER BY started_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return {"episodes": [dict(r) for r in rows]}


def reconstruct_episode(episode_id: str) -> dict[str, Any]:
    """An episode + the timeline events linked to it, in chronological order."""
    migrate()
    with _conn() as db:
        ep = db.execute(
            "SELECT id, summary, started_at, ended_at FROM episodes WHERE id=?", (episode_id,)
        ).fetchone()
        if not ep:
            return {"ok": False, "error": "episode not found"}
        links = db.execute(
            "SELECT event_type, event_id, source_table FROM episode_events WHERE episode_id=?",
            (episode_id,),
        ).fetchall()
        # hydrate timeline-event links (the common case) into full events
        tl_ids = [ln["event_id"] for ln in links if ln["source_table"] == "timeline_events" and ln["event_id"]]
        events: list[dict] = []
        if tl_ids:
            qs = ",".join("?" for _ in tl_ids)
            rows = db.execute(
                f"""SELECT id, event_type, content, timestamp, importance, project_id
                    FROM timeline_events WHERE id IN ({qs}) ORDER BY timestamp ASC""",
                tl_ids,
            ).fetchall()
            events = [dict(r) for r in rows]
    return {
        "ok": True,
        "episode": dict(ep),
        "events": events,
        "links": [dict(ln) for ln in links],
    }
