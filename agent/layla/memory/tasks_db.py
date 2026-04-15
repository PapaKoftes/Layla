"""Persistent coordinator / agent tasks (SQLite)."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")


def create_task(*, goal: str, conversation_id: str = "") -> str:
    migrate()
    tid = str(uuid.uuid4())
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """
            INSERT INTO tasks (id, goal, status, plan_json, results_json, execution_state_json, conversation_id, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (tid, goal or "", "running", "{}", "[]", "{}", (conversation_id or "").strip(), now, now),
        )
        db.commit()
    return tid


def update_task(
    task_id: str,
    *,
    status: str | None = None,
    plan: dict | list | None = None,
    results: list | None = None,
    execution_state: dict | None = None,
) -> None:
    migrate()
    tid = (task_id or "").strip()
    if not tid:
        return
    fields: list[str] = []
    vals: list[Any] = []
    if status is not None:
        fields.append("status=?")
        vals.append(status)
    if plan is not None:
        fields.append("plan_json=?")
        vals.append(json.dumps(plan, default=str))
    if results is not None:
        fields.append("results_json=?")
        vals.append(json.dumps(results, default=str))
    if execution_state is not None:
        fields.append("execution_state_json=?")
        vals.append(json.dumps(execution_state, default=str))
    if not fields:
        return
    fields.append("updated_at=?")
    vals.append(utcnow().isoformat())
    vals.append(tid)
    with _conn() as db:
        db.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", vals)
        db.commit()


def get_task(task_id: str) -> dict[str, Any] | None:
    migrate()
    tid = (task_id or "").strip()
    if not tid:
        return None
    with _conn() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_tasks(*, limit: int = 50, conversation_id: str | None = None) -> list[dict[str, Any]]:
    migrate()
    lim = max(1, min(200, int(limit)))
    with _conn() as db:
        if conversation_id is not None and str(conversation_id).strip():
            rows = db.execute(
                "SELECT * FROM tasks WHERE conversation_id=? ORDER BY updated_at DESC LIMIT ?",
                (str(conversation_id).strip(), lim),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?",
                (lim,),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    for k in ("plan_json", "results_json", "execution_state_json"):
        raw = d.get(k)
        if isinstance(raw, str) and raw:
            try:
                d[k] = json.loads(raw)
            except Exception:
                pass
    return d
