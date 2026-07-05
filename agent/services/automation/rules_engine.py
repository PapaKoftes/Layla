"""Event-driven automation engine (BL-233) — a rule layer over the existing watchers.

A *rule* is `event → action`: "on a new file matching `*.md` → run macro X", "on a git
commit → reindex", "on a schedule tick → summarize the day". Rules are stored in SQLite;
`dispatch_event(event_type, payload)` finds enabled rules whose trigger matches and runs
their action. The file watcher (`knowledge_watcher`) and git/scheduler surfaces emit events
into here, so automation composes with what Layla already does rather than re-plumbing it.

Actions reuse existing capabilities (macros BL-231, timeline BL-234, the repo indexer) and
are each wrapped so one failing rule never blocks the others or the emitting watcher.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

EVENT_TYPES = ("file_created", "file_modified", "git_commit", "schedule", "manual")
ACTION_TYPES = ("run_macro", "record_timeline", "reindex", "log")


def _data_dir() -> Path:
    """Layla's data directory (same LAYLA_DATA_DIR the memory layer uses)."""
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / ".layla"


def _db_path() -> Path:
    return _data_dir() / "automation.db"


@contextmanager
def _db():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                event TEXT NOT NULL,
                match_glob TEXT DEFAULT '',
                action TEXT NOT NULL,
                params TEXT DEFAULT '{}',
                enabled INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                last_fired REAL,
                fire_count INTEGER DEFAULT 0
            )"""
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── CRUD ─────────────────────────────────────────────────────────────────────
def add_rule(
    name: str, event: str, action: str, *,
    match_glob: str = "", params: dict | None = None, enabled: bool = True,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}
    if event not in EVENT_TYPES:
        return {"ok": False, "error": f"unknown event {event!r}; one of {EVENT_TYPES}"}
    if action not in ACTION_TYPES:
        return {"ok": False, "error": f"unknown action {action!r}; one of {ACTION_TYPES}"}
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO rule (name, event, match_glob, action, params, enabled, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (name, event, match_glob, action, json.dumps(params or {}), int(enabled), time.time()),
        )
        return {"ok": True, "id": cur.lastrowid}


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "name": r["name"], "event": r["event"], "match_glob": r["match_glob"],
        "action": r["action"], "params": json.loads(r["params"] or "{}"),
        "enabled": bool(r["enabled"]), "created_at": r["created_at"],
        "last_fired": r["last_fired"], "fire_count": r["fire_count"],
    }


def list_rules() -> list[dict]:
    with _db() as conn:
        return [_row(r) for r in conn.execute("SELECT * FROM rule ORDER BY created_at DESC").fetchall()]


def set_enabled(rule_id: int, enabled: bool) -> dict[str, Any]:
    with _db() as conn:
        cur = conn.execute("UPDATE rule SET enabled=? WHERE id=?", (int(enabled), int(rule_id)))
        return {"ok": cur.rowcount > 0, "enabled": enabled}


def delete_rule(rule_id: int) -> dict[str, Any]:
    with _db() as conn:
        cur = conn.execute("DELETE FROM rule WHERE id=?", (int(rule_id),))
        return {"ok": cur.rowcount > 0}


# ── dispatch ─────────────────────────────────────────────────────────────────
def _matches(rule: dict, payload: dict) -> bool:
    glob = rule.get("match_glob") or ""
    if not glob:
        return True
    target = str(payload.get("path") or payload.get("target") or "")
    return fnmatch.fnmatch(target, glob) or fnmatch.fnmatch(Path(target).name, glob)


def _run_action(rule: dict, payload: dict) -> dict[str, Any]:
    action = rule["action"]
    params = dict(rule.get("params") or {})
    try:
        if action == "log":
            logger.info("automation rule %r fired: %s", rule["name"], payload)
            return {"ok": True, "action": "log"}
        if action == "record_timeline":
            from layla.memory.user_profile import add_timeline_event
            content = params.get("content") or f"automation: {rule['name']} ({payload.get('path','')})"
            eid = add_timeline_event(
                content, event_type=params.get("event_type", "life_event"),
                importance=float(params.get("importance", 0.4)),
            )
            return {"ok": eid != -1, "action": "record_timeline", "event_id": eid}
        if action == "run_macro":
            macro = params.get("macro")
            if not macro:
                return {"ok": False, "error": "run_macro needs params.macro"}
            from services.skills.macros import replay_macro
            # rule enablement is the operator's standing confirmation to run this
            res = replay_macro(macro, params=params.get("params") or {}, confirm=True)
            return {"ok": res.get("ok", False), "action": "run_macro", "macro": macro, "result": res}
        if action == "reindex":
            from services.workspace.repo_indexer import index_workspace_repo
            root = params.get("root") or payload.get("root") or "."
            res = index_workspace_repo(root)  # best-effort
            return {"ok": True, "action": "reindex", "root": str(root), "indexed": res.get("indexed", 0)}
    except Exception as e:  # noqa: BLE001
        logger.warning("automation action %s failed: %s", action, e)
        return {"ok": False, "action": action, "error": str(e)}
    return {"ok": False, "error": f"unhandled action {action!r}"}


def dispatch_event(event_type: str, payload: dict | None = None) -> dict[str, Any]:
    """Fire all enabled rules whose trigger matches. Never raises — best-effort."""
    payload = payload or {}
    fired: list[dict] = []
    try:
        with _db() as conn:
            rules = [_row(r) for r in conn.execute(
                "SELECT * FROM rule WHERE enabled=1 AND event=?", (event_type,)
            ).fetchall()]
    except Exception as e:  # noqa: BLE001
        logger.debug("automation dispatch skipped: %s", e)
        return {"ok": True, "fired": 0, "results": []}

    for rule in rules:
        if not _matches(rule, payload):
            continue
        res = _run_action(rule, payload)
        fired.append({"rule": rule["name"], "id": rule["id"], **res})
        try:
            with _db() as conn:
                conn.execute(
                    "UPDATE rule SET last_fired=?, fire_count=fire_count+1 WHERE id=?",
                    (time.time(), rule["id"]),
                )
        except Exception:
            pass
    return {"ok": True, "event": event_type, "fired": len(fired), "results": fired}
