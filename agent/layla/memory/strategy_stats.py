"""SQLite aggregates for strategy success/fail by task type and aspect/strategy label."""
from __future__ import annotations

from typing import Any

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow


def record_strategy_stat(task_type: str, strategy: str, *, success: bool) -> None:
    migrate()
    tt = (task_type or "general").strip()[:120] or "general"
    st = (strategy or "unknown").strip()[:120] or "unknown"
    now = utcnow().isoformat()
    succ_inc = 1 if success else 0
    fail_inc = 0 if success else 1
    with _conn() as db:
        db.execute(
            """
            INSERT INTO strategy_stats (task_type, strategy, success_count, fail_count, last_updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(task_type, strategy) DO UPDATE SET success_count = success_count + excluded.success_count,
              fail_count = fail_count + excluded.fail_count,
              last_updated_at = excluded.last_updated_at
            """,
            (tt, st, succ_inc, fail_inc, now),
        )
        db.commit()


def get_preferred_strategy(task_type: str, *, min_samples: int = 5) -> str | None:
    """Strategy label with highest success rate for this task_type (goal prefix), min N samples."""
    migrate()
    tt = (task_type or "general").strip()[:120] or "general"
    with _conn() as db:
        rows = db.execute(
            "SELECT strategy, success_count, fail_count FROM strategy_stats WHERE task_type=?",
            (tt,),
        ).fetchall()
    best: str | None = None
    best_rate = -1.0
    for r in rows:
        st = str(r["strategy"] or "")
        sc = int(r["success_count"] or 0)
        fc = int(r["fail_count"] or 0)
        n = sc + fc
        if n < min_samples:
            continue
        rate = sc / n if n else 0.0
        if rate > best_rate:
            best_rate = rate
            best = st
    return best


def get_strategy_stat_row(task_type: str, strategy: str) -> dict[str, Any] | None:
    migrate()
    tt = (task_type or "general").strip()[:120] or "general"
    st = (strategy or "unknown").strip()[:120] or "unknown"
    with _conn() as db:
        row = db.execute(
            "SELECT task_type, strategy, success_count, fail_count, last_updated_at "
            "FROM strategy_stats WHERE task_type=? AND strategy=?",
            (tt, st),
        ).fetchone()
    if not row:
        return None
    return {
        "task_type": row["task_type"],
        "strategy": row["strategy"],
        "success_count": int(row["success_count"]),
        "fail_count": int(row["fail_count"]),
        "last_updated_at": row["last_updated_at"],
    }
