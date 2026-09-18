"""Workspace code-intelligence walks must skip dependency/venv trees.

build_workspace_graph runs on the system-head build EVERY turn (via get_workspace_dependency_context).
It used to rglob("*.py") skipping only .git/__pycache__/node_modules, so a workspace containing a
virtualenv (.venv with tens of thousands of installed-package .py files) made every turn read the whole
venv — a multi-minute stall on any real Python project a friend points Layla at. These tests pin the
skip so a venv/cache tree can never re-enter the walk.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.workspace.workspace_index import _skip_walk, build_workspace_graph  # noqa: E402


def test_skip_walk_skips_venv_and_cache_dirs_but_keeps_source(tmp_path):
    root = tmp_path
    assert _skip_walk(root / ".venv" / "Lib" / "site-packages" / "pip" / "__init__.py", root) is True
    assert _skip_walk(root / "venv" / "x.py", root) is True
    assert _skip_walk(root / ".mypy_cache" / "x.py", root) is True
    assert _skip_walk(root / "node_modules" / "m" / "x.py", root) is True
    # real source is kept
    assert _skip_walk(root / "src" / "app.py", root) is False
    # a FILE (not dir) named like a skip dir is kept — only directory components are matched
    assert _skip_walk(root / "venv.py", root) is False
    assert _skip_walk(root / "src" / "node_modules.py", root) is False


def test_build_workspace_graph_ignores_a_venv_tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def real_function():\n    return 1\n", encoding="utf-8")
    venv_pkg = tmp_path / ".venv" / "Lib" / "site-packages" / "somepkg"
    venv_pkg.mkdir(parents=True)
    (venv_pkg / "vendored.py").write_text("def vendored_function():\n    return 2\n", encoding="utf-8")

    build_workspace_graph(str(tmp_path))
    from services.workspace import workspace_index as wi

    # Assert at the FILE level (symbol extraction depends on tree-sitter, which may be absent): the real
    # source file is indexed, and NOTHING from the .venv tree is. That is the skip contract.
    files = {(n.get("file") or "") for n in wi._workspace_graph.values()}
    assert "src/app.py" in files, "the real source file must be indexed"
    assert not any(fp.startswith(".venv") or "/.venv/" in fp or "vendored" in fp for fp in files), (
        f"a .venv file leaked into the workspace graph: {sorted(files)}"
    )
