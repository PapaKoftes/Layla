"""Decision memory (BL-235) — persist deliberations so Layla can recall *why* it chose.

The cognitive workspace generates candidate approaches, evaluates them, and picks one.
That reasoning was previously thrown away. This store keeps, for each real decision:
the chosen option, the rationale, the rejected alternatives, any assumptions, and the
goal/context — so a later turn (or a human) can ask "why did we do it this way?" and get
a grounded answer instead of a re-derivation. Plain SQLite, next to the other stores.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


def _data_dir() -> Path:
    """Layla's data directory (same LAYLA_DATA_DIR the memory layer uses)."""
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / ".layla"


def _db_path() -> Path:
    return _data_dir() / "decisions.db"


@contextmanager
def _db():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS decision (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal TEXT NOT NULL,
                chosen TEXT NOT NULL,
                chosen_name TEXT DEFAULT '',
                rationale TEXT DEFAULT '',
                alternatives TEXT DEFAULT '[]',
                assumptions TEXT DEFAULT '[]',
                context TEXT DEFAULT '',
                project TEXT DEFAULT '',
                created_at REAL NOT NULL
            )"""
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_decision(
    goal: str,
    chosen: str,
    *,
    chosen_name: str = "",
    rationale: str = "",
    alternatives: list | None = None,
    assumptions: list | None = None,
    context: str = "",
    project: str = "",
) -> dict[str, Any]:
    """Persist one decision. `alternatives` = the rejected options (each ideally a dict)."""
    goal = (goal or "").strip()
    chosen = (chosen or "").strip()
    if not goal or not chosen:
        return {"ok": False, "error": "goal and chosen required"}
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO decision (goal, chosen, chosen_name, rationale, alternatives,"
            " assumptions, context, project, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                goal[:2000], chosen[:200], chosen_name[:200], (rationale or "")[:2000],
                json.dumps(alternatives or []), json.dumps(assumptions or []),
                (context or "")[:2000], (project or "")[:400], time.time(),
            ),
        )
        return {"ok": True, "id": cur.lastrowid}


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "goal": r["goal"],
        "chosen": r["chosen"],
        "chosen_name": r["chosen_name"],
        "rationale": r["rationale"],
        "alternatives": json.loads(r["alternatives"] or "[]"),
        "assumptions": json.loads(r["assumptions"] or "[]"),
        "context": r["context"],
        "project": r["project"],
        "created_at": r["created_at"],
    }


def list_decisions(*, limit: int = 50, project: str = "") -> list[dict]:
    with _db() as conn:
        if project:
            rows = conn.execute(
                "SELECT * FROM decision WHERE project=? ORDER BY created_at DESC, id DESC LIMIT ?",
                (project, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM decision ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row(r) for r in rows]


def search_decisions(query: str, *, limit: int = 20) -> list[dict]:
    """Substring search over goal + rationale — 'why did we choose X?'."""
    q = f"%{(query or '').strip()}%"
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM decision WHERE goal LIKE ? OR rationale LIKE ? OR chosen LIKE ?"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (q, q, q, limit),
        ).fetchall()
        return [_row(r) for r in rows]


def get_decision(decision_id: int) -> dict | None:
    with _db() as conn:
        r = conn.execute("SELECT * FROM decision WHERE id=?", (int(decision_id),)).fetchone()
        return _row(r) if r else None
