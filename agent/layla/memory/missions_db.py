"""Missions Db — Layla SQLite."""
import json
import logging
import sqlite3

from layla.time_utils import utcnow

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")


# ── mission chains (evolution layer) ───────────────────────────────────────

def create_mission_chain(
    chain_id: str,
    mission_type: str,
    goal_summary: str,
    parent_mission_id: str | None = None,
    capability_domains: list[str] | None = None,
) -> None:
    migrate()
    now = utcnow().isoformat()
    domains_json = json.dumps(capability_domains or []) if capability_domains else "[]"
    with _conn() as db:
        db.execute(
            """INSERT INTO mission_chains (id, parent_mission_id, mission_type, goal_summary, status, capability_domains, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (chain_id, parent_mission_id or "", mission_type, goal_summary, "pending", domains_json, now),
        )
        db.commit()


def get_pending_mission_chains() -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT * FROM mission_chains WHERE status='pending' ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def complete_mission_chain(chain_id: str, outcome_summary: str) -> None:
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "UPDATE mission_chains SET status='completed', outcome_summary=?, completed_at=? WHERE id=?",
            (outcome_summary, now, chain_id),
        )
        db.commit()


# ── missions (v1.1 — long-running agent tasks) ────────────────────────────────

def save_mission(mission: dict) -> None:
    """Persist a mission to the missions table."""
    migrate()
    now = utcnow().isoformat()
    mission_id = mission.get("id", "")
    goal = mission.get("goal", "")
    plan = mission.get("plan") or []
    status = mission.get("status", "pending")
    current_step = int(mission.get("current_step", 0))
    results = mission.get("results") or []
    workspace_root = mission.get("workspace_root", "")
    allow_write = 1 if mission.get("allow_write") else 0
    allow_run = 1 if mission.get("allow_run") else 0
    plan_json = json.dumps(plan)
    results_json = json.dumps(results)
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO missions
               (id, goal, plan_json, status, current_step, results_json, created_at, updated_at,
                workspace_root, allow_write, allow_run)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mission_id,
                goal,
                plan_json,
                status,
                current_step,
                results_json,
                mission.get("created_at", now),
                mission.get("updated_at", now),
                workspace_root,
                allow_write,
                allow_run,
            ),
        )
        db.commit()


def get_mission(mission_id: str) -> dict | None:
    """Fetch a mission by id."""
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
    if not row:
        return None
    try:
        plan = json.loads(row["plan_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        plan = []
    try:
        results = json.loads(row["results_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        results = []
    return {
        "id": row["id"],
        "goal": row["goal"],
        "plan": plan,
        "status": row["status"],
        "current_step": int(row["current_step"] or 0),
        "results": results,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "workspace_root": row["workspace_root"] or "",
        "allow_write": bool(row["allow_write"]),
        "allow_run": bool(row["allow_run"]),
    }


def update_mission_status(mission_id: str, status: str) -> None:
    """Update mission status."""
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "UPDATE missions SET status=?, updated_at=? WHERE id=?",
            (status, now, mission_id),
        )
        db.commit()


def update_mission_progress(
    mission_id: str,
    status: str | None = None,
    current_step: int | None = None,
    results: list | None = None,
) -> None:
    """Update mission progress: status, current_step, results."""
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        if status is not None:
            db.execute("UPDATE missions SET status=?, updated_at=? WHERE id=?", (status, now, mission_id))
        if current_step is not None:
            db.execute("UPDATE missions SET current_step=?, updated_at=? WHERE id=?", (current_step, now, mission_id))
        if results is not None:
            results_json = json.dumps(results)
            db.execute("UPDATE missions SET results_json=?, updated_at=? WHERE id=?", (results_json, now, mission_id))
        db.commit()


def get_active_missions(limit: int = 5) -> list[dict]:
    """Fetch missions with status running or pending, for mission_worker."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT id FROM missions WHERE status IN ('running','pending') ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for row in rows:
        m = get_mission(row["id"])
        if m:
            out.append(m)
    return out


def get_missions(limit: int = 50, status_filter: str | None = None) -> list[dict]:
    """Fetch missions for listing; optionally filter by status."""
    migrate()
    with _conn() as db:
        if status_filter:
            rows = db.execute(
                "SELECT id FROM missions WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status_filter, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id FROM missions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    out = []
    for row in rows:
        m = get_mission(row["id"])
        if m:
            out.append(m)
    return out


def save_background_task(task: dict) -> None:
    """Create or replace a durable background task row."""
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO background_tasks
               (id, conversation_id, goal, aspect_id, status, priority, result, error,
                created_at, started_at, finished_at, updated_at, kind, progress_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.get("task_id", ""),
                task.get("conversation_id", "") or "",
                task.get("goal", "") or "",
                task.get("aspect_id", "") or "",
                task.get("status", "queued") or "queued",
                int(task.get("priority", 0) or 0),
                task.get("result", "") or "",
                task.get("error", "") or "",
                task.get("created_at", now) or now,
                task.get("started_at", "") or "",
                task.get("finished_at", "") or "",
                now,
                (task.get("kind") or "background") or "background",
                task.get("progress_json", "[]") or "[]",
            ),
        )
        db.commit()


def update_background_task(
    task_id: str,
    *,
    status: str | None = None,
    result: str | None = None,
    error: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    progress_json: str | None = None,
) -> None:
    """Update mutable background task fields."""
    migrate()
    updates: list[str] = []
    args: list = []
    if status is not None:
        updates.append("status=?")
        args.append(status)
    if result is not None:
        updates.append("result=?")
        args.append(result)
    if error is not None:
        updates.append("error=?")
        args.append(error)
    if started_at is not None:
        updates.append("started_at=?")
        args.append(started_at)
    if finished_at is not None:
        updates.append("finished_at=?")
        args.append(finished_at)
    if progress_json is not None:
        updates.append("progress_json=?")
        args.append(progress_json)
    updates.append("updated_at=?")
    args.append(utcnow().isoformat())
    args.append(task_id)
    with _conn() as db:
        db.execute(f"UPDATE background_tasks SET {', '.join(updates)} WHERE id=?", tuple(args))
        db.commit()


def get_background_task(task_id: str) -> dict | None:
    """Fetch one persisted background task."""
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM background_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def list_background_tasks(limit: int = 200) -> list[dict]:
    """List persisted background tasks by newest first."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM background_tasks ORDER BY created_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [dict(r) for r in rows]


