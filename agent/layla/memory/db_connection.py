"""SQLite connection for Layla persistent memory."""
import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "layla.db"


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


def _conn() -> sqlite3.Connection:
    """
    Return an optimized SQLite connection.
    - WAL mode: readers don't block writers, writers don't block readers.
    - SYNCHRONOUS=NORMAL: safe + fast (still durable on power failure with WAL).
    - CACHE_SIZE=-32000: 32 MB page cache per connection.
    - TEMP_STORE=MEMORY: temp tables in RAM.
    - MMAP_SIZE=256MB: memory-mapped I/O for read-heavy paths.
    """
    c = sqlite3.connect(str(_resolve_db_path()), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-32000")   # 32 MB
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA mmap_size=268435456")  # 256 MB
    c.execute("PRAGMA busy_timeout=5000")   # 5 s wait on SQLITE_BUSY
    return c
