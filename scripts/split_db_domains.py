"""Split agent/layla/memory/db.py API body into domain modules; rewrite db.py as barrel.

Line ranges: (start_1based, end_exclusive_1based) — same convention as Python slice on1-based line numbers:
  lines[start-1 : end-1] wrong — use lines[start-1 : end_excl] where end_excl is first line NOT included.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / "agent" / "layla" / "memory"
DB_PY = MEM / "db.py"
_src = DB_PY.read_text(encoding="utf-8")
if "re-exports domain modules" in _src[:2500]:
    raise SystemExit(
        "db.py is already a barrel file. Restore the pre-split monolith from git, "
        "run split_db_phase3a.py if needed, then run this script once."
    )
lines = _src.splitlines(keepends=True)
nlines = len(lines)

# (filename, [(start_1b, end_excl_1b), ...])
CHUNKS: list[tuple[str, list[tuple[int, int]]]] = [
    ("learnings.py", [(24, 363)]),
    ("plans_db.py", [(363, 425), (1763, nlines + 1)]),
    ("audit_session.py", [(425, 531)]),
    ("conversations.py", [(531, 709)]),
    ("projects_db.py", [(709, 843), (1628, 1711)]),
    ("user_profile.py", [(843, 1140)]),
    ("capabilities_db.py", [(1140, 1360)]),
    ("missions_db.py", [(1360, 1628)]),
    ("telemetry_db.py", [(1711, 1763)]),
]

HEADER_LEARNINGS = '''"""Learnings and spaced-repetition helpers (SQLite)."""
import hashlib
import json
import logging
import sqlite3

from layla.time_utils import utcnow

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")

'''

HEADER_STD = '''"""{title} — Layla SQLite."""
import json
import logging
import sqlite3

from layla.time_utils import utcnow

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")

'''


def _collect_body(ranges: list[tuple[int, int]]) -> str:
    parts: list[str] = []
    for start, end_excl in ranges:
        parts.append("".join(lines[start - 1 : end_excl - 1]))
    return "\n".join(parts)


def _defs_and_assigns(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("__"):
                    names.append(t.id)
    return names


def main() -> None:
    for fname, ranges in CHUNKS:
        body = _collect_body(ranges)
        if fname == "learnings.py":
            header = HEADER_LEARNINGS
        else:
            title = fname.replace(".py", "").replace("_", " ").title()
            header = HEADER_STD.format(title=title)
        (MEM / fname).write_text(header + "\n" + body.lstrip("\n"), encoding="utf-8")

    blocks: list[str] = [
        '"""',
        "SQLite persistent memory for Layla — re-exports domain modules.",
        "",
        "Tables and behavior unchanged; see layla/memory/migrations.py for schema.",
        '"""',
        "from layla.memory.db_connection import _conn",
        "from layla.memory.migrations import migrate",
        "",
    ]

    all_names: list[str] = ["_conn", "migrate"]
    for fname, _ in CHUNKS:
        mod = fname[:-3]
        defnames = [n for n in _defs_and_assigns(MEM / fname) if n != "logger"]
        joined = ",\n    ".join(defnames)
        blocks.append(f"from layla.memory.{mod} import (")
        blocks.append(f"    {joined},")
        blocks.append(")")
        blocks.append("")
        for n in defnames:
            if n not in all_names:
                all_names.append(n)

    blocks.append("__all__ = [")
    for n in all_names:
        blocks.append(f"    {repr(n)},")
    blocks.append("]")
    blocks.append("")

    DB_PY.write_text("\n".join(blocks) + "\n", encoding="utf-8")
    print("OK:", [c[0] for c in CHUNKS])


if __name__ == "__main__":
    main()
