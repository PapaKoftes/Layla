"""Phase 4: the geometry_read_file / gcode_analyze agent tools (registration + behavior)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.tools.domains.geometry import TOOLS as GEOM_META  # noqa: E402
from layla.tools.impl import geometry as g  # noqa: E402


def test_new_tools_registered():
    for name in ("geometry_read_file", "gcode_analyze"):
        assert name in GEOM_META, f"{name} missing from geometry tool metadata"
        assert GEOM_META[name]["description"]
        assert GEOM_META[name]["require_approval"] is False  # read-only


def test_geometry_read_file_tool(tmp_path, monkeypatch):
    cq = pytest.importorskip("cadquery")
    monkeypatch.setattr(g, "inside_sandbox", lambda p: True)  # bypass sandbox for the fixture path
    step = tmp_path / "flange.step"
    cq.exporters.export(
        cq.Workplane("XY").circle(30).extrude(5)
        .faces(">Z").workplane().polarArray(radius=20, startAngle=0, angle=360, count=4).hole(5),
        str(step))
    r = g.geometry_read_file(str(step))
    assert r["ok"] is True
    assert r["recognized_features"]["hole_count"] == 4
    assert any(p["type"] == "bolt_circle" for p in r["recognized_features"]["patterns"])


def test_geometry_read_file_rejects_outside_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "inside_sandbox", lambda p: False)
    r = g.geometry_read_file(str(tmp_path / "x.step"))
    assert r["ok"] is False and "sandbox" in r["error"]


def test_gcode_analyze_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "inside_sandbox", lambda p: True)
    nc = tmp_path / "danger.nc"
    nc.write_text("G21 G90\nM3 S1000\nG0 Z-1\nG0 X10 Y10\nG1 X0 Y0 F200\nG0 Z5\n", encoding="utf-8")
    r = g.gcode_analyze(str(nc))
    assert r["ok"] is True
    assert r["cut_moves"] >= 1
    assert r["safety"]["rapid_below_z0"] >= 1   # rapid plunge + traverse in stock
    assert "lint" in r
