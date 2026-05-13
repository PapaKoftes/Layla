"""
Per-guild configuration for Layla Discord Bot.

Stores guild-specific preferences in a SQLite database (separate from Layla's main DB).
Each guild can configure: default aspect, allowed channels, admin roles, TTS, max response length.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla.discord")

_DB_PATH = Path(__file__).resolve().parent / "guild_config.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """Get or create the guild config database connection."""
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
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                default_aspect TEXT DEFAULT '',
                allowed_channels TEXT DEFAULT '[]',
                admin_roles TEXT DEFAULT '[]',
                tts_enabled INTEGER DEFAULT 1,
                music_enabled INTEGER DEFAULT 1,
                max_response_length INTEGER DEFAULT 1900,
                auto_respond INTEGER DEFAULT 0,
                embed_responses INTEGER DEFAULT 1,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        _conn.commit()
        return _conn


# ── CRUD operations ──────────────────────────────────────────────────────────


def get_config(guild_id: int) -> dict[str, Any]:
    """Get configuration for a guild. Returns defaults if not configured."""
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row is None:
        return _defaults(guild_id)
    cols = [desc[0] for desc in conn.execute("SELECT * FROM guild_config LIMIT 0").description]
    d = dict(zip(cols, row))
    # Parse JSON fields
    d["allowed_channels"] = _parse_json_list(d.get("allowed_channels", "[]"))
    d["admin_roles"] = _parse_json_list(d.get("admin_roles", "[]"))
    d["tts_enabled"] = bool(d.get("tts_enabled", 1))
    d["music_enabled"] = bool(d.get("music_enabled", 1))
    d["auto_respond"] = bool(d.get("auto_respond", 0))
    d["embed_responses"] = bool(d.get("embed_responses", 1))
    return d


def set_config(guild_id: int, **kwargs) -> dict[str, Any]:
    """Set configuration fields for a guild. Returns updated config."""
    conn = _get_conn()
    current = get_config(guild_id)

    # Merge updates
    for key, value in kwargs.items():
        if key in current and key != "guild_id":
            current[key] = value

    # Serialize JSON fields
    allowed_channels = json.dumps(current.get("allowed_channels", []))
    admin_roles = json.dumps(current.get("admin_roles", []))

    with _lock:
        conn.execute("""
            INSERT INTO guild_config (guild_id, default_aspect, allowed_channels, admin_roles,
                                     tts_enabled, music_enabled, max_response_length,
                                     auto_respond, embed_responses, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(guild_id) DO UPDATE SET
                default_aspect = excluded.default_aspect,
                allowed_channels = excluded.allowed_channels,
                admin_roles = excluded.admin_roles,
                tts_enabled = excluded.tts_enabled,
                music_enabled = excluded.music_enabled,
                max_response_length = excluded.max_response_length,
                auto_respond = excluded.auto_respond,
                embed_responses = excluded.embed_responses,
                updated_at = excluded.updated_at
        """, (
            guild_id,
            current.get("default_aspect", ""),
            allowed_channels,
            admin_roles,
            int(current.get("tts_enabled", True)),
            int(current.get("music_enabled", True)),
            current.get("max_response_length", 1900),
            int(current.get("auto_respond", False)),
            int(current.get("embed_responses", True)),
        ))
        conn.commit()

    return get_config(guild_id)


def delete_config(guild_id: int) -> bool:
    """Delete configuration for a guild."""
    conn = _get_conn()
    with _lock:
        cursor = conn.execute("DELETE FROM guild_config WHERE guild_id = ?", (guild_id,))
        conn.commit()
        return cursor.rowcount > 0


def list_guilds() -> list[int]:
    """List all guild IDs with saved configuration."""
    conn = _get_conn()
    with _lock:
        rows = conn.execute("SELECT guild_id FROM guild_config").fetchall()
    return [row[0] for row in rows]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _defaults(guild_id: int) -> dict[str, Any]:
    """Default configuration for a guild."""
    return {
        "guild_id": guild_id,
        "default_aspect": "",
        "allowed_channels": [],
        "admin_roles": [],
        "tts_enabled": True,
        "music_enabled": True,
        "max_response_length": 1900,
        "auto_respond": False,
        "embed_responses": True,
    }


def _parse_json_list(raw: str | list) -> list:
    """Safely parse a JSON list string."""
    if isinstance(raw, list):
        return raw
    try:
        result = json.loads(raw or "[]")
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def is_channel_allowed(guild_id: int, channel_id: int) -> bool:
    """Check if a channel is allowed for bot responses. Empty list = all channels allowed."""
    cfg = get_config(guild_id)
    allowed = cfg.get("allowed_channels", [])
    if not allowed:
        return True  # No restrictions
    return channel_id in allowed


def get_default_aspect(guild_id: int) -> str:
    """Get the default aspect for a guild. Empty string = use Layla's default."""
    cfg = get_config(guild_id)
    return cfg.get("default_aspect", "")


def should_use_embeds(guild_id: int) -> bool:
    """Check if this guild wants embed-formatted responses."""
    cfg = get_config(guild_id)
    return cfg.get("embed_responses", True)


def close_db() -> None:
    """Close the database connection (cleanup)."""
    global _conn
    with _lock:
        if _conn:
            _conn.close()
            _conn = None
