"""Deterministic machining IR from DXF (layla.geometry.machining_ir)."""
from __future__ import annotations

from pathlib import Path

import pytest

from layla.geometry import machining_ir as mir


def test_plan_toolpath_order_holes_then_contours():
    feats = [
        {"id": "c1", "type": "contour", "perimeter": 10.0},
        {"id": "h2", "type": "hole", "radius": 5.0},
        {"id": "h1", "type": "hole", "radius": 2.0},
        {"id": "c2", "type": "contour", "perimeter": 20.0},
    ]
    order = mir.plan_toolpath_order(feats)
    assert order[:2] == ["h1", "h2"]
    assert "c2" in order and "c1" in order
    assert order.index("c2") < order.index("c1")


def test_build_machine_steps_preview():
    feats = [
        {"id": "h1", "type": "hole", "layer": "0", "radius": 1.0},
        {"id": "p1", "type": "contour", "layer": "cut", "perimeter": 100.0},
    ]
    order = mir.plan_toolpath_order(feats)
    steps = mir.build_machine_steps_preview(feats, order)
    assert len(steps) == 2
    assert steps[0]["op"] == "drill_or_pocket_circle"
    assert steps[1]["op"] == "profile_cut_2d"


def test_build_machining_ir_missing_file(tmp_path: Path):
    p = tmp_path / "missing.dxf"
    out = mir.build_machining_ir(str(p))
    assert out["ok"] is True
    assert out["feature_count"] == 0
    assert out["features"] == []


def test_extract_features_minimal_dxf(tmp_path: Path):
    ezdxf = pytest.importorskip("ezdxf")

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_circle((0, 0), radius=5, dxfattribs={"layer": "holes"})
    p = tmp_path / "t.dxf"
    doc.saveas(str(p))
    feats = mir.extract_features_from_dxf(p)
    assert len(feats) == 1
    assert feats[0]["type"] == "hole"
    assert feats[0]["radius"] == 5.0
