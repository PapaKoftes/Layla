"""Telemetry Db — Layla SQLite."""
import json
import logging
import sqlite3

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

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


def log_model_outcome(
    model_used: str,
    task_type: str | None,
    success: int,
    score: float | None,
    latency_ms: float | None,
) -> None:
    """Append one model outcome row (for adaptive routing)."""
    migrate()
    ts = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """
            INSERT INTO model_outcomes (ts, model_used, task_type, success, score, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                (model_used or "").strip(),
                task_type,
                int(success),
                float(score) if score is not None else None,
                float(latency_ms) if latency_ms is not None else None,
            ),
        )
        db.commit()


def get_model_success_rates(min_count: int = 5) -> dict:
    """
    Return {model_used: {task_type: {success_rate, avg_score, count}}}.
    Used by services.model_router for soft routing bias.
    """
    migrate()
    mc = max(1, min(int(min_count), 1000))
    with _conn() as db:
        cur = db.execute(
            """
            SELECT
                model_used,
                COALESCE(task_type, '') AS task_type,
                COUNT(*) AS n,
                AVG(COALESCE(score, NULL)) AS avg_score,
                AVG(CASE WHEN success != 0 THEN 1.0 ELSE 0.0 END) AS success_rate
            FROM model_outcomes
            GROUP BY model_used, COALESCE(task_type, '')
            HAVING COUNT(*) >= ?
            """,
            (mc,),
        )
        rows = cur.fetchall()
    out: dict = {}
    for r in rows:
        m = r["model_used"]
        tt = r["task_type"] or "default"
        out.setdefault(m, {})[tt] = {
            "success_rate": float(r["success_rate"] or 0.0),
            "avg_score": float(r["avg_score"]) if r["avg_score"] is not None else None,
            "count": int(r["n"] or 0),
        }
    return out


