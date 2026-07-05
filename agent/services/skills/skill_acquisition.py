"""Skill acquisition from tasks (BL-238) — learn a reusable skill from a good run.

When a task succeeds, its tool/step sequence is a reusable procedure. This turns that
sequence into a named, executable **learned skill**: the steps are stored as a macro
(BL-231, which handles validation + `{{param}}` replay through the live tool registry)
and a `learned_skills` row records the skill's identity — name, what task it solves, and
a link to its macro. Learned skills extend the skill surface beyond installed packs:
they're discoverable, invocable, and grow from what Layla actually did.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_SLUG = re.compile(r"[^a-z0-9]+")
_STOP = {"the", "a", "an", "to", "of", "for", "and", "in", "on", "with", "please", "can", "you", "my"}


def _data_dir() -> Path:
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / ".layla"


def _db_path() -> Path:
    return _data_dir() / "learned_skills.db"


@contextmanager
def _db():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS learned_skill (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                goal TEXT DEFAULT '',
                macro_name TEXT NOT NULL,
                step_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                use_count INTEGER DEFAULT 0,
                last_used REAL
            )"""
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def suggest_name(goal: str) -> str:
    """A stable kebab-case skill name derived from the task goal."""
    words = [w for w in _SLUG.sub(" ", (goal or "").lower()).split() if w and w not in _STOP]
    slug = "-".join(words[:5]) or "learned-skill"
    return slug[:60]


def acquire_from_run(
    state: dict,
    *,
    name: str = "",
    description: str = "",
    min_steps: int = 2,
) -> dict[str, Any]:
    """Learn a skill from a finished run's successful tool steps."""
    from services.skills.macros import extract_steps_from_run, record_macro

    steps = extract_steps_from_run(state or {})
    if len(steps) < min_steps:
        return {"ok": False, "error": f"need at least {min_steps} successful tool steps (got {len(steps)})"}

    goal = str((state or {}).get("original_goal") or (state or {}).get("objective") or "").strip()
    name = (name or "").strip() or suggest_name(goal)
    description = description or (goal[:200] if goal else f"learned skill: {name}")

    macro_name = f"skill:{name}"
    mac = record_macro(macro_name, steps, description=description, source_run=str((state or {}).get("run_id") or ""))
    if not mac.get("ok"):
        # a macro by that name may already exist — treat as re-learning the same skill
        return {"ok": False, "error": mac.get("error", "could not store skill steps")}

    with _db() as conn:
        try:
            conn.execute(
                "INSERT INTO learned_skill (name, description, goal, macro_name, step_count, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (name, description, goal, macro_name, len(steps), time.time()),
            )
        except sqlite3.IntegrityError:
            return {"ok": False, "error": f"a learned skill named {name!r} already exists"}
    return {"ok": True, "name": name, "macro": macro_name, "steps": len(steps), "description": description}


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "name": r["name"], "description": r["description"], "goal": r["goal"],
        "macro_name": r["macro_name"], "step_count": r["step_count"],
        "created_at": r["created_at"], "use_count": r["use_count"], "last_used": r["last_used"],
    }


def list_learned_skills() -> list[dict]:
    with _db() as conn:
        return [_row(r) for r in conn.execute(
            "SELECT * FROM learned_skill ORDER BY last_used DESC, created_at DESC"
        ).fetchall()]


def get_learned_skill(name: str) -> dict | None:
    with _db() as conn:
        r = conn.execute("SELECT * FROM learned_skill WHERE name=?", (name,)).fetchone()
        return _row(r) if r else None


def forget_skill(name: str) -> dict[str, Any]:
    """Remove a learned skill and its backing macro."""
    skill = get_learned_skill(name)
    if not skill:
        return {"ok": False, "error": "not found"}
    from services.skills.macros import delete_macro
    delete_macro(skill["macro_name"])
    with _db() as conn:
        conn.execute("DELETE FROM learned_skill WHERE name=?", (name,))
    return {"ok": True, "forgot": name}


def invoke_skill(name: str, *, params: dict | None = None, confirm: bool = False) -> dict[str, Any]:
    """Run a learned skill by replaying its backing macro."""
    skill = get_learned_skill(name)
    if not skill:
        return {"ok": False, "error": "skill not found"}
    from services.skills.macros import replay_macro
    res = replay_macro(skill["macro_name"], params=params or {}, confirm=confirm)
    if confirm and res.get("ok"):
        with _db() as conn:
            conn.execute(
                "UPDATE learned_skill SET use_count=use_count+1, last_used=? WHERE name=?",
                (time.time(), name),
            )
    return res
