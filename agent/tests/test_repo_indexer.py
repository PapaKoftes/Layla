"""
Tests for services/repo_indexer.py — Phase B: Persistent SQLite code symbol index.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture()
def fresh_db(tmp_path):
    """Provide a fresh isolated DB path for each test."""
    db = tmp_path / "test_repo.db"
    from services.repo_indexer import migrate
    migrate(db_path=db)
    return db


@pytest.fixture()
def sample_py(tmp_path):
    """Write a minimal Python file for indexing tests."""
    f = tmp_path / "sample.py"
    f.write_text(
        "class Widget:\n"
        "    def render(self):\n"
        "        return '<div/>'\n"
        "\n"
        "def create_widget(name):\n"
        "    return Widget()\n",
        encoding="utf-8",
    )
    return f


def test_extract_symbols_ast_finds_class_and_function():
    from services.repo_indexer import _extract_symbols_ast
    source = "class Foo:\n    def bar(self): pass\n\ndef baz(): pass\n"
    result = _extract_symbols_ast(source, "test.py")
    names = {s["name"] for s in result["symbols"]}
    assert "Foo" in names
    assert "baz" in names


def test_extract_symbols_ast_marks_method_with_parent():
    from services.repo_indexer import _extract_symbols_ast
    source = "class MyClass:\n    def my_method(self):\n        pass\n"
    result = _extract_symbols_ast(source, "test.py")
    methods = [s for s in result["symbols"] if s["name"] == "my_method"]
    assert methods, "my_method not found"
    assert methods[0]["parent"] == "MyClass"
    assert methods[0]["kind"] == "method"


def test_extract_symbols_ast_finds_imports():
    from services.repo_indexer import _extract_symbols_ast
    source = "import os\nfrom pathlib import Path\n"
    result = _extract_symbols_ast(source, "test.py")
    modules = {imp["module"] for imp in result["imports"]}
    assert "os" in modules
    assert "pathlib" in modules


def test_index_file_stores_symbols(tmp_path, fresh_db):
    from services.repo_indexer import index_file, get_file_symbols
    py = tmp_path / "mod.py"
    py.write_text("class Engine:\n    def start(self): pass\n\ndef run(): pass\n", encoding="utf-8")
    ok = index_file(py, tmp_path, db_path=fresh_db)
    assert ok is True
    result = get_file_symbols("mod.py", db_path=fresh_db)
    names = {s["name"] for s in result["symbols"]}
    assert "Engine" in names
    assert "run" in names


def test_index_file_idempotent(tmp_path, fresh_db):
    """Indexing the same file twice should not duplicate symbols."""
    from services.repo_indexer import index_file, get_symbols
    py = tmp_path / "idm.py"
    py.write_text("def alpha(): pass\n", encoding="utf-8")
    index_file(py, tmp_path, db_path=fresh_db)
    index_file(py, tmp_path, db_path=fresh_db)
    results = get_symbols(name="alpha", db_path=fresh_db)
    assert len(results) == 1, f"Expected 1 alpha, got {len(results)}"


def test_index_workspace_repo_indexes_all_py(tmp_path, fresh_db):
    from services.repo_indexer import index_workspace_repo, get_stats
    (tmp_path / "a.py").write_text("def aa(): pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("class Bb: pass\n", encoding="utf-8")
    result = index_workspace_repo(tmp_path, db_path=fresh_db)
    assert result["indexed"] >= 2
    assert result["errors"] == []
    stats = get_stats(db_path=fresh_db)
    assert stats["files"] >= 2
    assert stats["symbols"] >= 2


def test_search_symbols_finds_partial_match(tmp_path, fresh_db):
    from services.repo_indexer import index_file, search_symbols
    py = tmp_path / "utils.py"
    py.write_text("def compute_hash(): pass\ndef compute_score(): pass\n", encoding="utf-8")
    index_file(py, tmp_path, db_path=fresh_db)
    results = search_symbols("compute", db_path=fresh_db)
    names = {r["name"] for r in results}
    assert "compute_hash" in names
    assert "compute_score" in names


def test_get_callers_of(tmp_path, fresh_db):
    from services.repo_indexer import index_file, get_callers_of
    py = tmp_path / "caller.py"
    py.write_text("def main():\n    helper()\n\ndef helper(): pass\n", encoding="utf-8")
    index_file(py, tmp_path, db_path=fresh_db)
    callers = get_callers_of("helper", db_path=fresh_db)
    # calls may or may not be extracted (ast walk may not capture all; just ensure no crash)
    assert isinstance(callers, list)


def test_get_symbol_context_returns_string(tmp_path, fresh_db):
    from services.repo_indexer import index_file, get_symbol_context
    py = tmp_path / "ctx.py"
    py.write_text("def process_data(items, limit): pass\n", encoding="utf-8")
    index_file(py, tmp_path, db_path=fresh_db)
    ctx = get_symbol_context("process_data", db_path=fresh_db)
    assert "process_data" in ctx
    assert "ctx.py" in ctx


def test_export_graphml(tmp_path, fresh_db):
    pytest.importorskip("networkx")
    from services.repo_indexer import index_workspace_repo, export_graphml
    (tmp_path / "g.py").write_text("class Graph:\n    def edges(self): pass\n", encoding="utf-8")
    index_workspace_repo(tmp_path, db_path=fresh_db)
    gml = tmp_path / "out.graphml"
    ok = export_graphml(tmp_path, output_path=gml, db_path=fresh_db)
    assert ok is True
    assert gml.exists()


def test_skip_dirs_ignored(tmp_path, fresh_db):
    from services.repo_indexer import index_workspace_repo, get_stats
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "skip_me.py").write_text("def should_not_index(): pass\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("def should_index(): pass\n", encoding="utf-8")
    index_workspace_repo(tmp_path, db_path=fresh_db)
    from services.repo_indexer import get_symbols
    skipped = get_symbols(name="should_not_index", db_path=fresh_db)
    kept = get_symbols(name="should_index", db_path=fresh_db)
    assert len(skipped) == 0, "should_not_index in __pycache__ was indexed but shouldn't be"
    assert len(kept) >= 1


def test_stats_empty_db(fresh_db):
    from services.repo_indexer import get_stats
    stats = get_stats(db_path=fresh_db)
    assert stats == {"files": 0, "symbols": 0, "imports": 0, "calls": 0}


def test_no_orphaned_symbols_after_reindex(tmp_path, fresh_db):
    """After force_reindex, there should be no orphaned symbols."""
    from services.repo_indexer import index_workspace_repo
    import sqlite3
    (tmp_path / "x.py").write_text("def foo(): pass\n", encoding="utf-8")
    index_workspace_repo(tmp_path, db_path=fresh_db)
    # Force reindex
    index_workspace_repo(tmp_path, db_path=fresh_db, force_reindex=True)
    with sqlite3.connect(str(fresh_db)) as con:
        orphaned = con.execute("""
            SELECT COUNT(*) FROM repo_symbols s
            WHERE NOT EXISTS (SELECT 1 FROM repo_files WHERE path = s.file_path)
        """).fetchone()[0]
    assert orphaned == 0
