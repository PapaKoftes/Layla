"""Telemetry Db — Layla SQLite."""
import json
import logging
import sqlite3

from layla.time_utils import utcnow

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")


def log_telemetry_event(
    task_type: str | None,
    reasoning_mode: str | None,
    model_used: str | None,
    latency_ms: float,
    success: int,
    performance_mode: str | None,
) -> None:
    """Append one local telemetry row (privacy-safe; no external calls)."""
    migrate()
    ts = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """
            INSERT INTO telemetry_events (ts, task_type, reasoning_mode, model_used, latency_ms, success, performance_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, task_type, reasoning_mode, model_used, float(latency_ms), int(success), performance_mode),
        )
        db.commit()


def get_recent_telemetry_events(n: int = 50) -> list[dict]:
    """Return most recent telemetry rows as dicts (id, ts, task_type, ...)."""
    migrate()
    lim = max(1, min(int(n), 500))
    with _conn() as db:
        cur = db.execute(
            """
            SELECT id, ts, task_type, reasoning_mode, model_used, latency_ms, success, performance_mode
            FROM telemetry_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (lim,),
        )
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        out.append({
            "id": r["id"],
            "ts": r["ts"],
            "task_type": r["task_type"],
            "reasoning_mode": r["reasoning_mode"],
            "model_used": r["model_used"],
            "latency_ms": r["latency_ms"],
            "success": r["success"],
            "performance_mode": r["performance_mode"],
        })
    return out


