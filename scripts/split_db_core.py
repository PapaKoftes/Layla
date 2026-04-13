"""One-shot: extract layla/memory/db_core.py from db.py."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "agent" / "layla" / "memory" / "db.py"
lines = DB.read_text(encoding="utf-8").splitlines(keepends=True)
start_rest = None
for i, L in enumerate(lines):
    if L.startswith("def _migrate_learnings_json"):
        start_rest = i
        break
if start_rest is None:
    raise SystemExit("def _migrate_learnings_json not found")
core = "".join(lines[:start_rest])
rest = "".join(lines[start_rest:])
hdr = '"""SQLite connection and schema migration (split from db.py for maintainability)."""\n'
(DB.parent / "db_core.py").write_text(hdr + core, encoding="utf-8")
new_db = (
    '"""SQLite persistent memory for Layla.\n\n'
    "Table APIs; connection + migrate live in db_core.\n"
    '"""\n'
    "from __future__ import annotations\n\n"
    "import hashlib\n"
    "import json\n"
    "import logging\n"
    "import sqlite3\n"
    "from pathlib import Path\n\n"
    "from layla.time_utils import utcnow\n\n"
    "from layla.memory.db_core import _conn, migrate\n\n"
    'logger = logging.getLogger("layla")\n\n'
    + rest
)
DB.write_text(new_db, encoding="utf-8")
print("wrote db_core.py,", start_rest, "lines; db.py now starts with re-export")
