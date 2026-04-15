from __future__ import annotations

import json
from typing import Any

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow


def create_improvement(
    title: str,
    *,
    rationale: str = "",
    risk_level: str = "low",
    domain: str = "",
    instructions: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    migrate()
    t = (title or "").strip()
    if not t:
        return {"ok": False, "error": "title required"}
    instr_s = ""
    if isinstance(instructions, dict):
        instr_s = json.dumps(instructions, ensure_ascii=False)[:20000]
    elif isinstance(instructions, str):
        instr_s = instructions[:20000]
    now = utcnow().isoformat()
    with _conn() as db:
        cur = db.execute(
            """
            INSERT INTO self_improvement_proposals (created_at, status, title, rationale, risk_level, domain, instructions)
            VALUES (?,?,?,?,?,?,?)
            """,
            (now, "pending", t[:200], (rationale or "")[:2000], (risk_level or "low")[:20], (domain or "")[:60], instr_s),
        )
        db.commit()
        rid = int(cur.lastrowid or 0)
        row = db.execute("SELECT * FROM self_improvement_proposals WHERE id=?", (rid,)).fetchone()
    return {"ok": True, "proposal": dict(row) if row else {"id": rid}}


def list_improvements(status: str = "", limit: int = 50) -> list[dict[str, Any]]:
    migrate()
    st = (status or "").strip().lower()
    lim = max(1, min(int(limit or 50), 500))
    with _conn() as db:
        if st:
            rows = db.execute(
                "SELECT * FROM self_improvement_proposals WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (st, lim),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM self_improvement_proposals ORDER BY created_at DESC LIMIT ?",
                (lim,),
            ).fetchall()
    return [dict(r) for r in rows]


def set_improvement_status(ids: list[int], status: str) -> dict[str, Any]:
    migrate()
    st = (status or "").strip().lower()
    if st not in ("pending", "approved", "rejected", "applied"):
        return {"ok": False, "error": "invalid status"}
    clean = [int(i) for i in ids if int(i) > 0]
    if not clean:
        return {"ok": False, "error": "ids required"}
    with _conn() as db:
        q = ",".join("?" for _ in clean)
        cur = db.execute(f"UPDATE self_improvement_proposals SET status=? WHERE id IN ({q})", (st, *clean))
        db.commit()
    return {"ok": True, "updated": int(cur.rowcount or 0)}


def get_improvements_by_ids(ids: list[int]) -> list[dict[str, Any]]:
    migrate()
    clean = [int(i) for i in ids if int(i) > 0]
    if not clean:
        return []
    with _conn() as db:
        q = ",".join("?" for _ in clean)
        rows = db.execute(f"SELECT * FROM self_improvement_proposals WHERE id IN ({q})", tuple(clean)).fetchall()
    return [dict(r) for r in rows]

