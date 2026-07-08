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
    # Reclaim space over time on NEW databases (no-op on existing auto_vacuum=NONE files until a
    # full VACUUM). Paired with a periodic incremental_vacuum in the daily maintenance job so the
    # file tracks current data instead of only ever growing (audit: live DB never shrank).
    c.execute("PRAGMA auto_vacuum=INCREMENTAL")
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


def verify_and_recover_db() -> str:
    """Startup integrity gate (audit 3a). Run PRAGMA quick_check on the live DB; if it is
    corrupt, move it aside and restore the newest backup — otherwise migrate() throws, gets
    swallowed as a warning, and the app runs broken, failing on every DB-touching request.

    Returns: 'ok' (healthy or fresh install) | 'recovered' (restored from backup) |
    'corrupt_no_backup' (moved aside; a fresh DB will be created) | 'error'.
    """
    import shutil
    try:
        db_path = Path(_resolve_db_path())
        if not db_path.exists() or int(db_path.stat().st_size) == 0:
            return "ok"  # fresh install — nothing to check
        c = None
        try:
            c = sqlite3.connect(str(db_path))
            row = c.execute("PRAGMA quick_check").fetchone()
            if row and str(row[0]).lower() == "ok":
                return "ok"
            logger.critical("layla.db failed integrity check: %s", (row[0] if row else "unknown"))
        except Exception as e:
            logger.critical("layla.db could not be opened for integrity check: %s", e)
        finally:
            # MUST close before moving the file — an open handle locks it on Windows (WinError 32).
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass
        # Corrupt: move the bad file (+ WAL/SHM) aside, then restore the newest backup.
        bad = Path(str(db_path) + ".corrupt")
        try:
            shutil.move(str(db_path), str(bad))
            for suffix in ("-wal", "-shm"):
                s = Path(str(db_path) + suffix)
                if s.exists():
                    s.unlink()
        except Exception as e:
            logger.critical("could not move corrupt DB aside: %s", e)
            return "error"
        backup_dir = db_path.parent / "backups"
        backups = (sorted(backup_dir.glob("layla_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
                   if backup_dir.is_dir() else [])
        if backups:
            try:
                shutil.copy2(str(backups[0]), str(db_path))
                logger.critical("Recovered layla.db from backup %s (corrupt db saved as %s)",
                                backups[0].name, bad.name)
                return "recovered"
            except Exception as e:
                logger.critical("backup restore failed: %s (corrupt db saved as %s)", e, bad.name)
                return "error"
        logger.critical("No backup available to restore; a fresh DB will be created "
                        "(corrupt db saved as %s)", bad.name)
        return "corrupt_no_backup"
    except Exception as e:
        logger.error("verify_and_recover_db: %s", e)
        return "error"
