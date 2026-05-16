"""SQLite connection for Layla persistent memory.

P1-1: Thread-local connection pool — reuse connections within the same thread
instead of creating a fresh connection + 7 PRAGMAs on every call.
"""
import logging
import os
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger("layla")

_thread_local = threading.local()


def _default_db_path() -> Path:
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve() / "layla.db"
    return Path(__file__).resolve().parent.parent.parent.parent / "layla.db"


_DB_PATH = _default_db_path()


def _resolve_db_path() -> Path:
    """Use layla.memory.db._DB_PATH when tests (or host) patch the barrel module."""
    import sys

    m = sys.modules.get("layla.memory.db")
    if m is not None and hasattr(m, "_DB_PATH"):
        p = getattr(m, "_DB_PATH", None)
        if p is not None:
            try:
                return Path(p).expanduser().resolve()
            except Exception:
                return Path(p)
    return Path(_DB_PATH).expanduser().resolve()


def _make_connection() -> sqlite3.Connection:
    """Create a fresh optimized SQLite connection with all PRAGMAs set."""
    c = sqlite3.connect(str(_resolve_db_path()), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-32000")   # 32 MB
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA mmap_size=268435456")  # 256 MB
    c.execute("PRAGMA busy_timeout=5000")   # 5 s wait on SQLITE_BUSY
    c.execute("PRAGMA foreign_keys=ON")     # enforce FK constraints
    return c


def _conn() -> sqlite3.Connection:
    """Return an optimized SQLite connection, reusing per-thread when possible.

    Thread-local pooling avoids creating a new connection + running 8 PRAGMAs
    on every call (~100x faster for hot paths). Stale connections are detected
    via a lightweight ``SELECT 1`` probe.
    """
    existing = getattr(_thread_local, "connection", None)
    db_path = str(_resolve_db_path())
    if existing is not None:
        # Verify the connection is still alive and points to the right DB
        existing_path = getattr(_thread_local, "connection_path", None)
        if existing_path == db_path:
            try:
                existing.execute("SELECT 1")
                return existing
            except Exception:
                # Connection went stale — recreate
                try:
                    existing.close()
                except Exception:
                    pass
        else:
            # DB path changed (e.g. test isolation) — close old and reconnect
            try:
                existing.close()
            except Exception:
                pass

    c = _make_connection()
    _thread_local.connection = c
    _thread_local.connection_path = db_path
    return c


def close_thread_connection() -> None:
    """Explicitly close and release the connection for the current thread.

    Call this when a thread is about to exit (e.g. in shutdown hooks) to avoid
    resource leaks. Safe to call multiple times or when no connection exists.
    """
    existing = getattr(_thread_local, "connection", None)
    if existing is not None:
        try:
            existing.close()
        except Exception:
            pass
        _thread_local.connection = None
        _thread_local.connection_path = None
