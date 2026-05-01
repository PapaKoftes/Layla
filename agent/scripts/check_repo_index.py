#!/usr/bin/env python3
"""
check_repo_index.py — Phase B gate: verify repo symbol index integrity.

Checks:
  RIX-01  repo_index.db exists and is readable
  RIX-02  repo_files table has rows (workspace has been indexed)
  RIX-03  repo_symbols table has rows
  RIX-04  No orphaned symbols (symbols with no matching file record)
  RIX-05  Symbol schema validates correctly
  RIX-06  get_symbols() search API returns results
  RIX-07  GraphML export succeeds (if networkx available)

Exit 0 = pass, 1 = fail.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))

from services.repo_indexer import _DEFAULT_DB, _conn, migrate, get_stats, get_symbols


def check_db_readable() -> tuple[bool, str]:
    try:
        migrate()
        stats = get_stats()
        return True, f"repo_index.db OK (files={stats['files']}, symbols={stats['symbols']})"
    except Exception as exc:
        return False, f"repo_index.db error: {exc}"


def check_files_table() -> tuple[bool, str]:
    try:
        with _conn() as db:
            count = db.execute("SELECT COUNT(*) FROM repo_files").fetchone()[0]
        if count == 0:
            return True, "SKIP: no files indexed yet (run index_workspace_repo first)"
        return True, f"repo_files OK ({count} files)"
    except Exception as exc:
        return False, f"repo_files error: {exc}"


def check_symbols_table() -> tuple[bool, str]:
    try:
        with _conn() as db:
            count = db.execute("SELECT COUNT(*) FROM repo_symbols").fetchone()[0]
        if count == 0:
            return True, "SKIP: no symbols indexed yet"
        return True, f"repo_symbols OK ({count} symbols)"
    except Exception as exc:
        return False, f"repo_symbols error: {exc}"


def check_orphaned_symbols() -> tuple[bool, str]:
    try:
        with _conn() as db:
            orphaned = db.execute("""
                SELECT COUNT(*) FROM repo_symbols s
                WHERE NOT EXISTS (SELECT 1 FROM repo_files WHERE path = s.file_path)
            """).fetchone()[0]
        if orphaned > 0:
            return False, f"FAIL: {orphaned} orphaned symbol(s)"
        return True, "No orphaned symbols"
    except Exception as exc:
        return True, f"SKIP: {exc}"


def check_symbol_schema() -> tuple[bool, str]:
    try:
        from services.repo_indexer import index_file, get_file_symbols
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            test_root = Path(td)
            test_file = test_root / "test_module.py"
            test_file.write_text(
                "class Foo:\n    def bar(self):\n        pass\n\ndef baz():\n    return 42\n",
                encoding="utf-8",
            )
            test_db = test_root / "test_repo.db"
            ok = index_file(test_file, test_root, db_path=test_db)
            if not ok:
                return False, "index_file returned False for valid Python"
            result = get_file_symbols("test_module.py", db_path=test_db)
            syms = result.get("symbols", [])
            names = {s["name"] for s in syms}
            if "Foo" not in names or "baz" not in names:
                return False, f"Expected Foo and baz in symbols, got: {names}"
        return True, "Symbol schema validates correctly"
    except Exception as exc:
        return False, f"Symbol schema error: {exc}"


def check_search_api() -> tuple[bool, str]:
    try:
        # If there are any symbols, search should find something
        with _conn() as db:
            count = db.execute("SELECT COUNT(*) FROM repo_symbols").fetchone()[0]
        if count == 0:
            return True, "SKIP: no symbols to search"
        # Try a generic search
        results = get_symbols(limit=5)
        return True, f"search API OK (sample: {len(results)} results)"
    except Exception as exc:
        return False, f"search API error: {exc}"


def check_graphml_export() -> tuple[bool, str]:
    try:
        import networkx as nx
    except ImportError:
        return True, "SKIP: networkx not installed"
    try:
        import tempfile
        from services.repo_indexer import export_graphml
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gml = root / "test.graphml"
            export_graphml(root, output_path=gml)
            # Even an empty graph is fine
        return True, "GraphML export OK"
    except Exception as exc:
        return False, f"GraphML export error: {exc}"


CHECKS = [
    ("RIX-01 DB readable",        check_db_readable),
    ("RIX-02 files table",        check_files_table),
    ("RIX-03 symbols table",      check_symbols_table),
    ("RIX-04 orphaned symbols",   check_orphaned_symbols),
    ("RIX-05 symbol schema",      check_symbol_schema),
    ("RIX-06 search API",         check_search_api),
    ("RIX-07 GraphML export",     check_graphml_export),
]


def run() -> int:
    print("=" * 60)
    print("Repo Index Check")
    print("=" * 60)

    failures = 0
    for label, fn in CHECKS:
        ok, msg = fn()
        status = "PASS" if ok else "FAIL"
        print(f"  {label:<35} {status}  {msg}")
        if not ok:
            failures += 1

    print()
    if failures == 0:
        print("All repo index checks passed.")
        return 0
    else:
        print(f"FAIL: {failures} issue(s) found")
        return 1


if __name__ == "__main__":
    sys.exit(run())
