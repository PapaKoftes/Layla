"""RL preference cache rows (SQLite). Used by services.rl_feedback."""

from __future__ import annotations

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow


def get_rl_preferences() -> list[dict]:
    """Return all rl_preferences rows as dicts."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT tool_name, score, hint, updated_at FROM rl_preferences ORDER BY score DESC",
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_rl_preference(tool_name: str, score: float, hint: str) -> None:
    """Insert or update an rl_preference row."""
    if not (tool_name or "").strip():
        return
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """INSERT INTO rl_preferences (tool_name, score, hint, updated_at)
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(tool_name) DO UPDATE SET score=excluded.score,
                 hint=excluded.hint, updated_at=excluded.updated_at""",
            (tool_name.strip(), float(score), (hint or ""), now),
        )
        db.commit()
