"""Phase 4: analyze_file() now returns REAL geometry/G-code reads, not 'intent from context'."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.file_understanding import analyze_file  # noqa: E402


def test_analyze_step_is_real_read(tmp_path):
    cq = pytest.importorskip("cadquery")
    step = tmp_path / "part.step"
    cq.exporters.export(
        cq.Workplane("XY").box(30, 20, 5).faces(">Z").workplane().hole(6), str(step))
    r = analyze_file(str(step))
    assert r.get("dimension") == "3d-brep"
    assert r["dims"] == [30.0, 20.0, 5.0]
    assert r["features"]["hole_count"] == 1


def test_analyze_stl_is_real_read(tmp_path):
    trimesh = pytest.importorskip("trimesh")
    stl = tmp_path / "m.stl"
    trimesh.creation.box(extents=[10.0, 10.0, 10.0]).export(str(stl))
    r = analyze_file(str(stl))
    assert r.get("dimension") == "3d-mesh"
    assert r["watertight"] is True and r["printable"] is True


def test_analyze_gcode_is_semantic(tmp_path):
    nc = tmp_path / "p.nc"
    nc.write_text("G21 G90\nM3 S1000\nG0 Z5\nG1 Z-1 F100\nG1 X10 Y0 F300\nG0 Z5\nM5\n", encoding="utf-8")
    r = analyze_file(str(nc))
    assert r["format"] == "G-code"
    assert r["semantics"]["cut_moves"] >= 2
    assert r["semantics"]["units"] == "mm"
    assert "lint" in r
