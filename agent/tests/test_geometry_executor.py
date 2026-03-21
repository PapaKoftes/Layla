"""Geometry executor (sandbox + optional ezdxf)."""

import tempfile
from pathlib import Path

import pytest


def test_execute_dxf_program_ezdxf():
    pytest.importorskip("ezdxf")

    from layla.geometry.executor import execute_program
    from layla.geometry.schema import parse_program

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = {"sandbox_root": str(root)}
        prog = parse_program(
            {
                "version": "1",
                "ops": [
                    {"op": "dxf_begin"},
                    {"op": "dxf_line", "x1": 0, "y1": 0, "x2": 10, "y2": 0},
                    {"op": "dxf_save", "path": "x.dxf"},
                ],
            }
        )
        r = execute_program(prog, str(root), "out", cfg=cfg)
        assert r.get("ok") is True
        assert (root / "out" / "x.dxf").exists()


def test_list_framework_status_shape():
    from layla.geometry.executor import list_framework_status

    st = list_framework_status({"sandbox_root": str(Path.home()), "geometry_frameworks_enabled": {"ezdxf": True}})
    assert "modules" in st
    assert "openscad" in st
