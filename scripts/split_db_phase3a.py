"""One-shot: Phase 3A split layla/memory/db.py into db_connection, migrations, db (APIs)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PY = ROOT / "agent" / "layla" / "memory" / "db.py"
lines = DB_PY.read_text(encoding="utf-8").splitlines(keepends=True)

# Original db.py: migrate() and helpers were lines 50–927 (1-based) → slice [49:928]
migrate_body = "".join(lines[49:928])
migrate_body = migrate_body.replace(
    'learnings_json = Path(__file__).resolve().parent.parent.parent.parent / "learnings.json"',
    'learnings_json = _DB_PATH.parent / "learnings.json"',
)

db_connection = '''"""SQLite connection for Layla persistent memory."""
import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "layla.db"


def _conn() -> sqlite3.Connection:
    """
    Return an optimized SQLite connection.
    - WAL mode: readers don't block writers, writers don't block readers.
    - SYNCHRONOUS=NORMAL: safe + fast (still durable on power failure with WAL).
    - CACHE_SIZE=-32000: 32 MB page cache per connection.
    - TEMP_STORE=MEMORY: temp tables in RAM.
    - MMAP_SIZE=256MB: memory-mapped I/O for read-heavy paths.
    """
    c = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-32000")   # 32 MB
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA mmap_size=268435456")  # 256 MB
    c.execute("PRAGMA busy_timeout=5000")   # 5 s wait on SQLITE_BUSY
    return c
'''

migrations_hdr = '''"""SQLite schema creation and migrations for Layla."""
import json
import logging
import sqlite3
import threading

from layla.time_utils import utcnow
from layla.memory.db_connection import _DB_PATH, _conn

logger = logging.getLogger("layla")

# Migration guard: run _migrate_impl at most once per process.
_MIGRATED = False
_MIGRATION_LOCK = threading.Lock()


'''

migrations_foot = '''

__all__ = ["migrate", "_MIGRATED", "_MIGRATION_LOCK"]
'''

(ROOT / "agent" / "layla" / "memory" / "migrations.py").write_text(
    migrations_hdr + migrate_body + migrations_foot,
    encoding="utf-8",
)

(ROOT / "agent" / "layla" / "memory" / "db_connection.py").write_text(db_connection, encoding="utf-8")

api_hdr = '''"""
SQLite persistent memory for Layla.

Tables:
  learnings        — replaces learnings.json for structured persistence
  study_plans      — topics Layla is studying
  wakeup_log       — session greeting history
  audit            — tool execution audit trail
  aspect_memories  — per-aspect long-term observations
"""
import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from layla.time_utils import utcnow

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")

'''

api_rest = "".join(lines[929:])
DB_PY.write_text(api_hdr + api_rest, encoding="utf-8")

print("Wrote db_connection.py, migrations.py, rewrote db.py (API tail)")
