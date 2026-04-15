"""Audit Session — Layla SQLite."""
import json
import logging
import sqlite3

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")


# ── wakeup log ─────────────────────────────────────────────────────────────

def log_wakeup(greeting: str, notes: str = "") -> None:
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO wakeup_log (timestamp, greeting, notes) VALUES (?,?,?)",
            (utcnow().isoformat(), greeting, notes),
        )
        db.commit()


def get_last_wakeup() -> dict | None:
    migrate()
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM wakeup_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ── audit ─────────────────────────────────────────────────────────────────

def log_audit(tool: str, args_summary: str, approved_by: str, result_ok: bool) -> None:
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO audit (timestamp, tool, args_summary, approved_by, result_ok) VALUES (?,?,?,?,?)",
            (utcnow().isoformat(), tool, args_summary[:200], approved_by, int(result_ok)),
        )
        db.commit()


def get_recent_audit(n: int = 10) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def save_session_prompt(prompt: str, aspect: str = "") -> None:
    migrate()
    text = (prompt or "")[:10000]
    asp = (aspect or "")[:128]
    if not text.strip():
        return
    with _conn() as db:
        db.execute(
            "INSERT INTO session_prompts (prompt, aspect) VALUES (?, ?)",
            (text, asp),
        )
        db.commit()


def get_recent_session_prompts(limit: int = 50) -> list[dict]:
    migrate()
    lim = max(1, min(200, int(limit)))
    with _conn() as db:
        rows = db.execute(
            "SELECT id, prompt, aspect, created_at FROM session_prompts ORDER BY id DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_tool_permission_grant(tool: str, pattern: str, scope: str = "permanent") -> str:
    """Store a tool + glob-like pattern the operator approved (e.g. shell + 'git *')."""
    import uuid
    migrate()
    gid = str(uuid.uuid4())
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO tool_permission_grants
               (id, tool, pattern, scope, created_at, expires_at) VALUES (?,?,?,?,?,?)""",
            (gid, tool[:128], pattern[:512], scope[:32], utcnow().isoformat(), ""),
        )
        db.commit()
    return gid


def tool_grant_matches(tool: str, command_line: str) -> bool:
    import fnmatch
    migrate()
    cmd = (command_line or "").strip()
    if not cmd:
        return False
    with _conn() as db:
        rows = db.execute(
            "SELECT pattern FROM tool_permission_grants WHERE tool=?",
            (tool,),
        ).fetchall()
    for r in rows:
        pat = (r["pattern"] or "").strip()
        if not pat:
            continue
        try:
            if fnmatch.fnmatch(cmd, pat) or fnmatch.fnmatch(cmd.lower(), pat.lower()):
                return True
        except Exception:
            if pat.rstrip("*") and cmd.lower().startswith(pat.rstrip("*").lower()):
                return True
    return False


