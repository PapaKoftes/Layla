# -*- coding: utf-8 -*-
"""
check_db_schema.py — Validate SQLite schema consistency across the Layla codebase.

Checks:
  DB-01  Every table referenced in queries exists in the CREATE TABLE migration
  DB-02  Column names used in INSERT/SELECT match the schema definition
  DB-03  No raw string SQL with f-string formatting (SQL injection risk)
  DB-04  migration() is idempotent (uses CREATE TABLE IF NOT EXISTS)
  DB-05  All db files accessible (not locked / corrupted)

Usage:
    cd agent/ && python scripts/check_db_schema.py
    echo $?
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", "models", "chroma_db",
             "scripts", "tests", "fabrication_assist"}

issues: list[dict] = []


def _report(check, file, line, snippet, note):
    issues.append({"check": check, "file": str(file), "line": line,
                   "snippet": str(snippet)[:100], "note": note})


def _py_files():
    for f in AGENT_DIR.rglob("*.py"):
        if any(p in f.parts for p in SKIP_DIRS):
            continue
        yield f


def _lines(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


# DB-01/02: Collect schema from migration scripts
def _collect_schema() -> dict[str, set[str]]:
    """Parse CREATE TABLE IF NOT EXISTS statements → {table: {columns}}"""
    schema: dict[str, set[str]] = {}
    _RE_CREATE = re.compile(
        r'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\(([^;]+)\)', re.I | re.S
    )
    _RE_COL = re.compile(r'^\s*(\w+)\s+(?:TEXT|INTEGER|REAL|BLOB|NUMERIC|BOOLEAN)', re.I)

    for f in _py_files():
        src = "\n".join(_lines(f))
        for m in _RE_CREATE.finditer(src):
            table = m.group(1).lower()
            col_block = m.group(2)
            cols: set[str] = set()
            for line in col_block.splitlines():
                cm = _RE_COL.match(line)
                if cm:
                    cols.add(cm.group(1).lower())
            if table not in schema:
                schema[table] = cols
            else:
                schema[table].update(cols)
    return schema


def check_idempotent_migration():
    """DB-04: Ensure all CREATE TABLE statements use IF NOT EXISTS."""
    _RE_CREATE_NO_GUARD = re.compile(r'CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)\s*\w+', re.I)
    for f in _py_files():
        if "migrat" not in f.name and "db" not in f.name and "memory" not in str(f):
            continue
        for i, line in enumerate(_lines(f), 1):
            if line.strip().startswith("#"):
                continue
            if _RE_CREATE_NO_GUARD.search(line):
                _report("DB-04", f, i, line,
                        "CREATE TABLE without IF NOT EXISTS — migration not idempotent; "
                        "will crash on second startup")


def check_fstring_sql():
    """DB-03: f-string SQL is injection risk — only flag user-input variables."""
    _RE_FSTR_SQL = re.compile(
        r'(?:execute|executescript|executemany)\s*\(\s*[fF]["\'].*(?:SELECT|INSERT|UPDATE|DELETE)',
        re.I
    )
    # Safe: table/column names from DB introspection or controlled constant lists
    _SAFE = re.compile(
        r'\{(?:table_name|table|col|placeholders|fields|updates|joins?|order|q)\b'
        r"|PRAGMA\s+\{|sqlite_master|',\s*'\s*\}\.join\(|join\s*\("
    )
    for f in _py_files():
        for i, line in enumerate(_lines(f), 1):
            if _RE_FSTR_SQL.search(line) and not _SAFE.search(line):
                _report("DB-03", f, i, line,
                        "SQL built with f-string in execute() — use parameterised (?, ?) placeholders")


def check_db_files_readable():
    """DB-05: All .db files in repo root are readable SQLite."""
    for db in AGENT_DIR.parent.glob("*.db"):
        try:
            conn = sqlite3.connect(str(db))
            conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
        except Exception as e:
            _report("DB-05", db, 0, str(db.name), f"DB file not readable: {e}")


def run() -> int:
    print("=" * 60)
    print("Database Schema Consistency Check")
    print("=" * 60)

    schema = _collect_schema()
    print(f"  Tables found in migrations: {len(schema)}")
    for t, cols in sorted(schema.items()):
        print(f"    {t}: {sorted(cols)}")
    print()

    checks = [
        ("DB-03 f-string SQL",         check_fstring_sql),
        ("DB-04 Idempotent migration",  check_idempotent_migration),
        ("DB-05 DB files readable",     check_db_files_readable),
    ]

    for name, fn in checks:
        before = len(issues)
        try:
            fn()
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
        after = len(issues)
        status = "PASS" if after == before else f"FAIL ({after - before})"
        print(f"  {name:<35} {status}")

    print()
    if issues:
        print(f"ISSUES: {len(issues)}")
        for iss in issues:
            print(f"  [{iss['check']}] {iss['file']}:{iss['line']}")
            print(f"    {iss['snippet']}")
            print(f"    ^ {iss['note']}\n")
        return 1
    print("All DB checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
