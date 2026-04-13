"""Projects Db — Layla SQLite."""
import json
import logging
import sqlite3

from layla.time_utils import utcnow

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")


# ── layla_projects (scoped agent presets) ─────────────────────────────────────

def create_project(
    name: str,
    workspace_root: str = "",
    aspect_default: str = "",
    skill_paths_json: str = "[]",
    system_preamble: str = "",
    project_id: str = "",
    cognition_extra_roots: str | list | None = None,
) -> dict:
    import json
    import uuid

    migrate()
    pid = (project_id or "").strip() or str(uuid.uuid4())
    now = utcnow().isoformat()
    nm = (name or "").strip() or "Untitled project"
    wr = (workspace_root or "").strip()
    ad = (aspect_default or "").strip()
    spj = (skill_paths_json or "").strip() or "[]"
    try:
        json.loads(spj)
    except Exception:
        spj = "[]"
    pre = (system_preamble or "").strip()[:8000]
    cog_ex = ""
    if isinstance(cognition_extra_roots, list):
        try:
            cog_ex = json.dumps(cognition_extra_roots)[:16000]
        except Exception:
            cog_ex = "[]"
    elif isinstance(cognition_extra_roots, str) and cognition_extra_roots.strip():
        cog_ex = cognition_extra_roots.strip()[:16000]
    with _conn() as db:
        db.execute(
            """INSERT INTO layla_projects
               (id, name, workspace_root, aspect_default, skill_paths_json, system_preamble, cognition_extra_roots, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (pid, nm, wr, ad, spj, pre, cog_ex, now, now),
        )
        db.commit()
        row = db.execute("SELECT * FROM layla_projects WHERE id=?", (pid,)).fetchone()
    return dict(row) if row else {"id": pid}


def list_projects(limit: int = 100) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM layla_projects ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_project(project_id: str) -> dict | None:
    migrate()
    pid = (project_id or "").strip()
    if not pid:
        return None
    with _conn() as db:
        row = db.execute("SELECT * FROM layla_projects WHERE id=?", (pid,)).fetchone()
    return dict(row) if row else None


def update_project(project_id: str, fields: dict) -> dict | None:
    migrate()
    pid = (project_id or "").strip()
    if not pid:
        return None
    cur = get_project(pid)
    if not cur:
        return None
    name = fields.get("name", cur.get("name", ""))
    workspace_root = fields.get("workspace_root", cur.get("workspace_root", ""))
    aspect_default = fields.get("aspect_default", cur.get("aspect_default", ""))
    skill_paths_json = fields.get("skill_paths_json", cur.get("skill_paths_json", "[]"))
    system_preamble = fields.get("system_preamble", cur.get("system_preamble", ""))
    cognition_extra_roots = fields.get("cognition_extra_roots", cur.get("cognition_extra_roots", ""))
    if isinstance(cognition_extra_roots, list):
        import json as _json

        try:
            cognition_extra_roots = _json.dumps(cognition_extra_roots)
        except Exception:
            cognition_extra_roots = "[]"
    cognition_extra_roots = (str(cognition_extra_roots or "").strip())[:16000]
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """UPDATE layla_projects SET name=?, workspace_root=?, aspect_default=?,
               skill_paths_json=?, system_preamble=?, cognition_extra_roots=?, updated_at=? WHERE id=?""",
            (
                (name or "").strip()[:200],
                (workspace_root or "").strip(),
                (aspect_default or "").strip(),
                (skill_paths_json or "[]").strip(),
                (system_preamble or "").strip()[:8000],
                cognition_extra_roots,
                now,
                pid,
            ),
        )
        db.commit()
    return get_project(pid)


def delete_project(project_id: str) -> bool:
    migrate()
    pid = (project_id or "").strip()
    if not pid:
        return False
    with _conn() as db:
        cur = db.execute("DELETE FROM layla_projects WHERE id=?", (pid,))
        db.commit()
        return cur.rowcount > 0


def set_conversation_project(conversation_id: str, project_id: str) -> bool:
    migrate()
    cid = (conversation_id or "").strip()
    if not cid:
        return False
    now = utcnow().isoformat()
    with _conn() as db:
        cur = db.execute(
            "UPDATE conversations SET project_id=?, updated_at=? WHERE id=?",
            ((project_id or "").strip(), now, cid),
        )
        db.commit()
        return cur.rowcount > 0



def get_project_context() -> dict:
    """Return current project context: project_name, domains (list), key_files (list), goals, progress, blockers, last_discussed."""
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM project_context WHERE id=1").fetchone()
    if not row:
        return {
            "project_name": "", "domains": [], "key_files": [], "goals": "", "lifecycle_stage": "",
            "progress": "", "blockers": "", "last_discussed": "", "updated_at": "",
        }
    try:
        domains = json.loads(row["domains"] or "[]")
    except (json.JSONDecodeError, TypeError):
        domains = []
    try:
        key_files = json.loads(row["key_files"] or "[]")
    except (json.JSONDecodeError, TypeError):
        key_files = []
    r = dict(row)
    return {
        "project_name": r.get("project_name") or "",
        "domains": domains,
        "key_files": key_files,
        "goals": r.get("goals") or "",
        "lifecycle_stage": (r.get("lifecycle_stage") or "").strip() or "",
        "progress": (r.get("progress") or "").strip() or "",
        "blockers": (r.get("blockers") or "").strip() or "",
        "last_discussed": (r.get("last_discussed") or "").strip() or "",
        "updated_at": r.get("updated_at") or "",
    }


PROJECT_LIFECYCLE_STAGES = ("idea", "planning", "prototype", "iteration", "execution", "reflection")


def set_project_context(
    project_name: str = "",
    domains: list[str] | None = None,
    key_files: list[str] | None = None,
    goals: str = "",
    lifecycle_stage: str = "",
    progress: str = "",
    blockers: str = "",
    last_discussed: str = "",
) -> None:
    """Update project context. lifecycle_stage: idea|planning|prototype|iteration|execution|reflection (North Star §3)."""
    migrate()
    now = utcnow().isoformat()
    cur = get_project_context()
    if project_name:
        cur["project_name"] = project_name
    if domains is not None:
        cur["domains"] = domains
    if key_files is not None:
        cur["key_files"] = key_files
    if goals:
        cur["goals"] = goals
    if lifecycle_stage and lifecycle_stage.strip().lower() in PROJECT_LIFECYCLE_STAGES:
        cur["lifecycle_stage"] = lifecycle_stage.strip().lower()
    if progress:
        cur["progress"] = progress.strip()
    if blockers:
        cur["blockers"] = blockers.strip()
    if last_discussed:
        cur["last_discussed"] = last_discussed.strip()
    cols = ["project_name", "domains", "key_files", "goals", "lifecycle_stage", "progress", "blockers", "last_discussed", "updated_at"]
    vals = (
        cur["project_name"], json.dumps(cur["domains"]), json.dumps(cur["key_files"]), cur["goals"],
        cur.get("lifecycle_stage", ""), cur.get("progress", ""), cur.get("blockers", ""), cur.get("last_discussed", ""), now,
    )
    with _conn() as db:
        try:
            placeholders = ", ".join(f"{c}=?" for c in cols)
            db.execute(f"UPDATE project_context SET {placeholders} WHERE id=1", vals)
        except sqlite3.OperationalError:
            # Fallback if new columns not yet migrated
            db.execute(
                """UPDATE project_context SET project_name=?, domains=?, key_files=?, goals=?, lifecycle_stage=?, updated_at=? WHERE id=1""",
                (cur["project_name"], json.dumps(cur["domains"]), json.dumps(cur["key_files"]), cur["goals"], cur.get("lifecycle_stage", ""), now),
            )
        db.commit()


