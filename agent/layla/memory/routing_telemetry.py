"""Routing telemetry DB — Layla SQLite (local-only)."""

from __future__ import annotations

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow


def log_route_telemetry(
    *,
    conversation_id: str | None,
    goal: str,
    task_type: str | None,
    is_meta_self: bool,
    has_workspace_signals: bool,
    decision_action: str | None,
    decision_tool: str | None,
    preflight_ok: bool | None,
    preflight_reason: str | None,
    final_status: str | None,
    parse_failed: bool,
) -> None:
    migrate()
    ts = utcnow().isoformat()
    g = (goal or "").strip()
    if len(g) > 2000:
        g = g[:2000] + "…"
    with _conn() as db:
        db.execute(
            """
            INSERT INTO route_telemetry
              (created_at, conversation_id, goal, task_type, is_meta_self, has_workspace_signals,
               decision_action, decision_tool, preflight_ok, preflight_reason, final_status, parse_failed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                (conversation_id or "").strip() or None,
                g,
                (task_type or "").strip() or None,
                int(bool(is_meta_self)),
                int(bool(has_workspace_signals)),
                (decision_action or "").strip() or None,
                (decision_tool or "").strip() or None,
                None if preflight_ok is None else int(bool(preflight_ok)),
                (preflight_reason or "").strip() or None,
                (final_status or "").strip() or None,
                int(bool(parse_failed)),
            ),
        )
        db.commit()


def get_recent_route_telemetry(n: int = 50) -> list[dict]:
    migrate()
    lim = max(1, min(int(n), 500))
    with _conn() as db:
        cur = db.execute(
            """
            SELECT
              id, created_at, conversation_id, goal, task_type,
              is_meta_self, has_workspace_signals,
              decision_action, decision_tool,
              preflight_ok, preflight_reason,
              final_status, parse_failed
            FROM route_telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            (lim,),
        )
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "conversation_id": r["conversation_id"],
                "goal": r["goal"],
                "task_type": r["task_type"],
                "is_meta_self": bool(r["is_meta_self"]),
                "has_workspace_signals": bool(r["has_workspace_signals"]),
                "decision_action": r["decision_action"],
                "decision_tool": r["decision_tool"],
                "preflight_ok": None if r["preflight_ok"] is None else bool(r["preflight_ok"]),
                "preflight_reason": r["preflight_reason"],
                "final_status": r["final_status"],
                "parse_failed": bool(r["parse_failed"]),
            }
        )
    return out

