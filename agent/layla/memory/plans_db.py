"""Plans Db — Layla SQLite."""
import json
import logging
import sqlite3

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")


# ── study plans ────────────────────────────────────────────────────────────

def save_study_plan(plan_id: str, topic: str, status: str = "active", domain_id: str | None = None) -> None:
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        try:
            db.execute(
                """INSERT INTO study_plans (id, topic, status, progress, created_at, domain_id)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status, domain_id=COALESCE(excluded.domain_id, study_plans.domain_id)""",
                (plan_id, topic, status, "[]", now, domain_id),
            )
        except sqlite3.OperationalError:
            db.execute(
                """INSERT INTO study_plans (id, topic, status, progress, created_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status""",
                (plan_id, topic, status, "[]", now),
            )
        db.commit()
    try:
        from services.personal_knowledge_graph import invalidate_personal_graph
        invalidate_personal_graph()
    except Exception:
        pass


def get_active_study_plans() -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM study_plans WHERE status='active'"
        ).fetchall()
    return [dict(r) for r in rows]


def get_plan_by_topic(topic: str) -> dict | None:
    """Return the active study plan with this topic (case-insensitive), or None."""
    if not (topic or "").strip():
        return None
    topic_clean = topic.strip().lower()
    for p in get_active_study_plans():
        if (p.get("topic") or "").strip().lower() == topic_clean:
            return p
    return None


def update_study_progress(plan_id: str, note: str) -> None:
    migrate()
    with _conn() as db:
        row = db.execute("SELECT progress FROM study_plans WHERE id=?", (plan_id,)).fetchone()
        if row:
            progress = json.loads(row["progress"] or "[]")
            progress.append({"note": note, "at": utcnow().isoformat()})
            try:
                max_entries = 50
                if isinstance(progress, list) and len(progress) > max_entries:
                    progress = progress[-max_entries:]
            except Exception:
                pass
            db.execute(
                "UPDATE study_plans SET progress=?, last_studied=? WHERE id=?",
                (json.dumps(progress), utcnow().isoformat(), plan_id),
            )
            db.commit()



# ── layla_plans (planning-first durable plans) ───────────────────────────────

_VALID_PLAN_STATUSES = frozenset({"draft", "approved", "executing", "done", "blocked"})


def create_layla_plan(
    goal: str,
    *,
    context: str = "",
    steps: list | None = None,
    workspace_root: str = "",
    conversation_id: str = "",
    status: str = "draft",
) -> str:
    """Insert a plan row; returns plan id (uuid)."""
    import uuid

    migrate()
    pid = str(uuid.uuid4())
    now = utcnow().isoformat()
    st = status if status in _VALID_PLAN_STATUSES else "draft"
    wr = normalize_workspace_root(workspace_root) if workspace_root else ""
    steps_json = json.dumps(steps if isinstance(steps, list) else [], default=str)
    with _conn() as db:
        db.execute(
            """INSERT INTO layla_plans
               (id, workspace_root, goal, context, steps_json, status, conversation_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (pid, wr, goal or "", context or "", steps_json, st, conversation_id or "", now, now),
        )
        db.commit()
    return pid


def get_layla_plan(plan_id: str) -> dict | None:
    migrate()
    pid = (plan_id or "").strip()
    if not pid:
        return None
    with _conn() as db:
        row = db.execute("SELECT * FROM layla_plans WHERE id=?", (pid,)).fetchone()
    if not row:
        return None
    try:
        steps = json.loads(row["steps_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        steps = []
    return {
        "id": row["id"],
        "workspace_root": row["workspace_root"] or "",
        "goal": row["goal"] or "",
        "context": row["context"] or "",
        "steps": steps if isinstance(steps, list) else [],
        "status": row["status"] or "draft",
        "conversation_id": row["conversation_id"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def update_layla_plan(
    plan_id: str,
    *,
    goal: str | None = None,
    context: str | None = None,
    steps: list | None = None,
    status: str | None = None,
    workspace_root: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    migrate()
    pid = (plan_id or "").strip()
    if not pid:
        return False
    existing = get_layla_plan(pid)
    if not existing:
        return False
    now = utcnow().isoformat()
    g = existing["goal"] if goal is None else goal
    c = existing["context"] if context is None else context
    s = existing["steps"] if steps is None else steps
    st = existing["status"] if status is None else status
    if st not in _VALID_PLAN_STATUSES:
        st = existing["status"]
    wr = existing["workspace_root"]
    if workspace_root is not None:
        wr = normalize_workspace_root(workspace_root) if workspace_root else ""
    conv = existing["conversation_id"] if conversation_id is None else conversation_id
    steps_json = json.dumps(s if isinstance(s, list) else [], default=str)
    with _conn() as db:
        db.execute(
            """UPDATE layla_plans SET goal=?, context=?, steps_json=?, status=?,
               workspace_root=?, conversation_id=?, updated_at=? WHERE id=?""",
            (g or "", c or "", steps_json, st, wr or "", conv or "", now, pid),
        )
        db.commit()
    return True


def list_layla_plans(
    *,
    workspace_root: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    migrate()
    lim = max(1, min(int(limit), 200))
    q = "SELECT id FROM layla_plans WHERE 1=1"
    args: list = []
    if workspace_root:
        q += " AND workspace_root = ?"
        args.append(normalize_workspace_root(workspace_root))
    if status and status in _VALID_PLAN_STATUSES:
        q += " AND status = ?"
        args.append(status)
    q += " ORDER BY updated_at DESC LIMIT ?"
    args.append(lim)
    with _conn() as db:
        rows = db.execute(q, tuple(args)).fetchall()
    out: list[dict] = []
    for r in rows:
        p = get_layla_plan(r["id"])
        if p:
            out.append(p)
    return out


def approve_layla_plan(plan_id: str) -> bool:
    """draft -> approved (idempotent if already approved)."""
    p = get_layla_plan(plan_id)
    if not p:
        return False
    if p["status"] in ("done", "blocked"):
        return False
    if p["status"] == "approved":
        return True
    return update_layla_plan(plan_id, status="approved")


def set_layla_plan_status(plan_id: str, status: str) -> bool:
    if status not in _VALID_PLAN_STATUSES:
        return False
    return update_layla_plan(plan_id, status=status)


def normalize_workspace_root(path: str) -> str:
    """Stable key for repo cognition (resolved absolute path)."""
    try:
        from pathlib import Path

        return str(Path(path).expanduser().resolve())
    except Exception:
        return (path or "").strip()


def save_repo_cognition_snapshot(row: dict) -> None:
    """Upsert one repo cognition digest row."""
    migrate()
    now = utcnow().isoformat()
    wr = normalize_workspace_root(row.get("workspace_root", "") or "")
    if not wr:
        return
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO repo_cognition_snapshots
               (workspace_root, label, fingerprint, pack_json, pack_markdown, file_manifest_json, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                wr,
                (row.get("label") or "")[:200],
                (row.get("fingerprint") or "")[:160],
                (row.get("pack_json") or "{}")[:500_000],
                (row.get("pack_markdown") or "")[:800_000],
                (row.get("file_manifest_json") or "[]")[:200_000],
                row.get("updated_at") or now,
            ),
        )
        db.commit()


def get_repo_cognition_snapshot(workspace_root: str) -> dict | None:
    migrate()
    wr = normalize_workspace_root(workspace_root)
    if not wr:
        return None
    with _conn() as db:
        row = db.execute("SELECT * FROM repo_cognition_snapshots WHERE workspace_root=?", (wr,)).fetchone()
    return dict(row) if row else None


def list_repo_cognition_snapshots(limit: int = 50) -> list[dict]:
    migrate()
    lim = max(1, min(int(limit), 200))
    with _conn() as db:
        rows = db.execute(
            "SELECT workspace_root, label, fingerprint, updated_at FROM repo_cognition_snapshots ORDER BY updated_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]
