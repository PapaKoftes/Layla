"""notebook_read_cells / notebook_edit_cell (nbformat)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

pytest.importorskip("nbformat")
import nbformat  # noqa: E402
from nbformat.v4 import new_code_cell, new_notebook  # noqa: E402


def test_notebook_read_and_edit_roundtrip(tmp_path):
    from layla.tools.registry import notebook_edit_cell, notebook_read_cells, set_effective_sandbox

    set_effective_sandbox(str(tmp_path))
    try:
        nb_path = tmp_path / "t.ipynb"
        nb = new_notebook(cells=[new_code_cell("x = 1\n")])
        nbformat.write(nb, str(nb_path))

        r = notebook_read_cells(str(nb_path))
        assert r.get("ok") is True
        assert r.get("cells") and r["cells"][0].get("source", "").strip() == "x = 1"

        r2 = notebook_edit_cell(str(nb_path), 0, "y = 2\n")
        assert r2.get("ok") is True
        r3 = notebook_read_cells(str(nb_path))
        assert "y = 2" in r3["cells"][0]["source"]
    finally:
        set_effective_sandbox(None)


def test_notebook_rejects_non_ipynb(tmp_path):
    from layla.tools.registry import notebook_read_cells, set_effective_sandbox

    set_effective_sandbox(str(tmp_path))
    try:
        p = tmp_path / "x.txt"
        p.write_text("nope", encoding="utf-8")

        r = notebook_read_cells(str(p))
        assert r.get("ok") is False
    finally:
        set_effective_sandbox(None)
