"""
Skill pack registry — SQLite-backed tracking of installed packs.

Tracks: name, version, git_url, manifest_hash, installed_at, last_run, health_status.
Provides CRUD operations and health check reporting.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_DB_PATH = Path.home() / ".layla" / "skill_registry.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """Get or create the registry database connection."""
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is not None:
            return _conn
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS installed_skills (
                name TEXT PRIMARY KEY,
                version TEXT NOT NULL DEFAULT '0.0.0',
                git_url TEXT DEFAULT '',
                manifest_hash TEXT DEFAULT '',
                pack_dir TEXT DEFAULT '',
                installed_at TEXT DEFAULT (datetime('now')),
                last_run TEXT DEFAULT '',
                health_status TEXT DEFAULT 'unknown',
                permissions TEXT DEFAULT '[]',
                error_message TEXT DEFAULT ''
            )
        """)
        _conn.commit()
        return _conn


def _manifest_hash(manifest: dict) -> str:
    """SHA-256 hash of serialized manifest (for change detection)."""
    raw = json.dumps(manifest, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── CRUD ─────────────────────────────────────────────────────────────────────


def register(
    name: str,
    version: str,
    pack_dir: str,
    manifest: dict | None = None,
    git_url: str = "",
    permissions: list[str] | None = None,
) -> None:
    """Register an installed skill pack."""
    conn = _get_conn()
    mhash = _manifest_hash(manifest) if manifest else ""
    perms = json.dumps(permissions or [])
    with _lock:
        conn.execute("""
            INSERT INTO installed_skills (name, version, git_url, manifest_hash, pack_dir, permissions, health_status)
            VALUES (?, ?, ?, ?, ?, ?, 'installed')
            ON CONFLICT(name) DO UPDATE SET
                version = excluded.version,
                git_url = excluded.git_url,
                manifest_hash = excluded.manifest_hash,
                pack_dir = excluded.pack_dir,
                permissions = excluded.permissions,
                health_status = 'installed',
                error_message = ''
        """, (name, version, git_url, mhash, pack_dir, perms))
        conn.commit()


def unregister(name: str) -> bool:
    """Remove a skill pack from the registry."""
    conn = _get_conn()
    with _lock:
        cursor = conn.execute("DELETE FROM installed_skills WHERE name = ?", (name,))
        conn.commit()
        return cursor.rowcount > 0


def get_pack(name: str) -> dict[str, Any] | None:
    """Get registry info for a pack. Returns None if not found."""
    conn = _get_conn()
    with _lock:
        row = conn.execute("SELECT * FROM installed_skills WHERE name = ?", (name,)).fetchone()
    if row is None:
        return None
    cols = ["name", "version", "git_url", "manifest_hash", "pack_dir",
            "installed_at", "last_run", "health_status", "permissions", "error_message"]
    d = dict(zip(cols, row))
    d["permissions"] = json.loads(d.get("permissions", "[]"))
    return d


def list_packs() -> list[dict[str, Any]]:
    """List all registered packs."""
    conn = _get_conn()
    with _lock:
        rows = conn.execute("SELECT * FROM installed_skills ORDER BY name").fetchall()
    cols = ["name", "version", "git_url", "manifest_hash", "pack_dir",
            "installed_at", "last_run", "health_status", "permissions", "error_message"]
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        d["permissions"] = json.loads(d.get("permissions", "[]"))
        result.append(d)
    return result


def update_health(name: str, status: str, error: str = "") -> None:
    """Update the health status of a pack."""
    conn = _get_conn()
    with _lock:
        conn.execute(
            "UPDATE installed_skills SET health_status = ?, error_message = ? WHERE name = ?",
            (status, error[:500], name),
        )
        conn.commit()


def update_last_run(name: str) -> None:
    """Update last_run timestamp."""
    conn = _get_conn()
    with _lock:
        conn.execute(
            "UPDATE installed_skills SET last_run = datetime('now') WHERE name = ?",
            (name,),
        )
        conn.commit()


def close_db() -> None:
    """Close the database connection."""
    global _conn
    with _lock:
        if _conn:
            _conn.close()
            _conn = None
