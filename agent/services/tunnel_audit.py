"""
tunnel_audit.py — Security audit logger for Layla's remote-access tunnel.

Every request that hits the tunnel (allow or deny) is recorded in a
dedicated SQLite database so the operator can review access patterns,
detect abuse, and satisfy compliance requirements.

Database: ~/.layla/tunnel_audit.db
Table:    tunnel_access_log
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
import threading
from datetime import timezone
from pathlib import Path

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Database location
# ---------------------------------------------------------------------------
_DB_DIR = Path.home() / ".layla"
_DB_PATH = _DB_DIR / "tunnel_audit.db"

# ---------------------------------------------------------------------------
# Thread-safety: one lock guards all write operations
# ---------------------------------------------------------------------------
_write_lock = threading.Lock()
_table_ready = False


def _get_connection() -> sqlite3.Connection:
    """Return a new SQLite connection with row-factory set to dict rows."""
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table() -> None:
    """Create the ``tunnel_access_log`` table if it does not already exist.

    Called automatically before every public function that touches the
    database.  Uses a module-level flag so the CREATE TABLE is executed at
    most once per process lifetime.
    """
    global _table_ready
    if _table_ready:
        return
    try:
        with _write_lock:
            if _table_ready:
                return
            conn = _get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tunnel_access_log (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT    NOT NULL,
                        client_ip TEXT,
                        path      TEXT,
                        method    TEXT,
                        token_id  TEXT,
                        result    TEXT    NOT NULL,
                        detail    TEXT
                    )
                    """
                )
                # Index on timestamp for efficient range queries / purges
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tunnel_log_ts
                    ON tunnel_access_log (timestamp)
                    """
                )
                conn.commit()
                _table_ready = True
            finally:
                conn.close()
    except Exception:
        logger.exception("tunnel_audit: failed to ensure table exists")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_access(
    ip: str,
    path: str,
    method: str,
    token_id: str | None,
    result: str,
    detail: str = "",
) -> None:
    """Record a single tunnel access attempt.

    Parameters
    ----------
    ip : str
        Client IP address.
    path : str
        Requested URL path.
    method : str
        HTTP method (GET, POST, ...).
    token_id : str | None
        First 8 characters of the SHA-256 token hash, or ``None`` if no
        token was presented.
    result : str
        ``"allow"`` or ``"deny"``.
    detail : str, optional
        Free-text detail (e.g. denial reason).
    """
    try:
        _ensure_table()
        ts = datetime.datetime.now(timezone.utc).isoformat()
        with _write_lock:
            conn = _get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO tunnel_access_log
                        (timestamp, client_ip, path, method, token_id, result, detail)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ts, ip, path, method, token_id, result, detail),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        logger.exception("tunnel_audit: failed to log access")


def query_log(
    days: int = 7,
    limit: int = 500,
    result_filter: str | None = None,
) -> list[dict]:
    """Return recent tunnel access log entries.

    Parameters
    ----------
    days : int
        How far back to look (default 7).
    limit : int
        Maximum rows to return (default 500).
    result_filter : str | None
        If ``"allow"`` or ``"deny"``, only return matching rows.

    Returns
    -------
    list[dict]
        Each dict has keys matching the table columns.
    """
    try:
        _ensure_table()
        since = (
            datetime.datetime.now(timezone.utc) - datetime.timedelta(days=days)
        ).isoformat()

        sql = "SELECT * FROM tunnel_access_log WHERE timestamp >= ?"
        params: list = [since]

        if result_filter in ("allow", "deny"):
            sql += " AND result = ?"
            params.append(result_filter)

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        conn = _get_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception:
        logger.exception("tunnel_audit: failed to query log")
        return []


def get_summary(days: int = 7) -> dict:
    """Return aggregate statistics for the last *days* days.

    Returns
    -------
    dict
        Keys: ``total_requests``, ``allowed``, ``denied``,
        ``unique_ips``, ``top_paths`` (list of ``[path, count]``),
        ``top_ips`` (list of ``[ip, count]``).
    """
    empty: dict = {
        "total_requests": 0,
        "allowed": 0,
        "denied": 0,
        "unique_ips": 0,
        "top_paths": [],
        "top_ips": [],
    }
    try:
        _ensure_table()
        since = (
            datetime.datetime.now(timezone.utc) - datetime.timedelta(days=days)
        ).isoformat()

        conn = _get_connection()
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)                                       AS total,
                    SUM(CASE WHEN result = 'allow' THEN 1 ELSE 0 END) AS allowed,
                    SUM(CASE WHEN result = 'deny'  THEN 1 ELSE 0 END) AS denied,
                    COUNT(DISTINCT client_ip)                      AS unique_ips
                FROM tunnel_access_log
                WHERE timestamp >= ?
                """,
                (since,),
            ).fetchone()

            top_paths = conn.execute(
                """
                SELECT path, COUNT(*) AS cnt
                FROM tunnel_access_log
                WHERE timestamp >= ?
                GROUP BY path
                ORDER BY cnt DESC
                LIMIT 5
                """,
                (since,),
            ).fetchall()

            top_ips = conn.execute(
                """
                SELECT client_ip, COUNT(*) AS cnt
                FROM tunnel_access_log
                WHERE timestamp >= ?
                GROUP BY client_ip
                ORDER BY cnt DESC
                LIMIT 5
                """,
                (since,),
            ).fetchall()

            return {
                "total_requests": row["total"] or 0,
                "allowed": row["allowed"] or 0,
                "denied": row["denied"] or 0,
                "unique_ips": row["unique_ips"] or 0,
                "top_paths": [[r["path"], r["cnt"]] for r in top_paths],
                "top_ips": [[r["client_ip"], r["cnt"]] for r in top_ips],
            }
        finally:
            conn.close()
    except Exception:
        logger.exception("tunnel_audit: failed to build summary")
        return empty


def purge_old(days: int = 90) -> int:
    """Delete log entries older than *days* days.

    Parameters
    ----------
    days : int
        Entries older than this many days are removed (default 90).

    Returns
    -------
    int
        Number of rows deleted.
    """
    try:
        _ensure_table()
        cutoff = (
            datetime.datetime.now(timezone.utc) - datetime.timedelta(days=days)
        ).isoformat()

        with _write_lock:
            conn = _get_connection()
            try:
                cursor = conn.execute(
                    "DELETE FROM tunnel_access_log WHERE timestamp < ?",
                    (cutoff,),
                )
                deleted = cursor.rowcount
                conn.commit()
                logger.info("tunnel_audit: purged %d entries older than %d days", deleted, days)
                return deleted
            finally:
                conn.close()
    except Exception:
        logger.exception("tunnel_audit: failed to purge old entries")
        return 0
