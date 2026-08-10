"""Golden tests for Phase-3 feature recognition (deterministic geometry, no model)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.geometry.feature_recognition import (  # noqa: E402
    detect_bolt_circle,
    detect_linear_array,
    detect_pockets,
    detect_rectangular_pattern,
    group_holes_by_size,
    recognize_features,
)


def _holes3d(centers, r):
    return {"holes": [{"center": [x, y, 0.0], "radius": r, "axis_dir": [0, 0, 1]} for x, y in centers]}


def _bolt_circle_centers(n, pcd_r):
    return [(pcd_r * math.cos(math.radians(k * 360 / n)),
             pcd_r * math.sin(math.radians(k * 360 / n))) for k in range(n)]


def test_bolt_circle():
    holes = _holes3d(_bolt_circle_centers(6, 25.0), 3.0)["holes"]
    holes = [{"x": h["center"][0], "y": h["center"][1], "z": 0, "r": h["radius"], "axis": (0, 0, 1)} for h in holes]
    bc = detect_bolt_circle(holes)
    assert bc is not None
    assert bc["count"] == 6
    assert abs(bc["pitch_circle_diameter"] - 50.0) < 1e-2
    assert abs(bc["center"][0]) < 1e-6 and abs(bc["center"][1]) < 1e-6
    assert bc["hole_diameter"] == 6.0


def test_rectangular_pattern_not_bolt_circle():
    holes = [{"x": x, "y": y, "z": 0, "r": 2.5, "axis": (0, 0, 1)}
             for x in (-20, 20) for y in (-10, 10)]
    assert detect_bolt_circle(holes) is None       # equidistant but NOT evenly angled
    rp = detect_rectangular_pattern(holes)
    assert rp is not None and rp["cols"] == 2 and rp["rows"] == 2 and rp["count"] == 4


def test_linear_array():
    holes = [{"x": x, "y": 0.0, "z": 0, "r": 2.0, "axis": (0, 0, 1)} for x in (0, 10, 20, 30)]
    la = detect_linear_array(holes)
    assert la is not None and la["count"] == 4 and abs(la["pitch"] - 10.0) < 1e-6


def test_group_by_size():
    holes = [{"x": 0, "y": 0, "z": 0, "r": 3.0, "axis": (0, 0, 1)},
             {"x": 5, "y": 0, "z": 0, "r": 3.0, "axis": (0, 0, 1)},
             {"x": 0, "y": 5, "z": 0, "r": 2.0, "axis": (0, 0, 1)}]
    groups = group_holes_by_size(holes)
    assert [g["diameter"] for g in groups] == [4.0, 6.0]
    assert [g["count"] for g in groups] == [1, 2]


def test_recognize_features_bolt_circle():
    geom = _holes3d(_bolt_circle_centers(4, 30.0), 2.5)
    geom["ok"] = True
    out = recognize_features(geom)
    assert out["hole_count"] == 4
    assert any(p["type"] == "bolt_circle" and p["count"] == 4 for p in out["patterns"])


def test_pocket_detection_2d():
    geom = {"ok": True, "features": [
        {"id": "poly_1", "type": "contour", "bbox": [0, 0, 50, 30], "perimeter": 160.0},
        {"id": "hole_1", "type": "hole", "center": [25, 15], "radius": 4.0},
    ]}
    pockets = detect_pockets(geom)
    assert len(pockets) == 1 and pockets[0]["islands"] == 1


def test_integration_step_bolt_circle(tmp_path):
    cq = pytest.importorskip("cadquery")
    from layla.geometry.geometry_read import read_geometry
    step = tmp_path / "flange.step"
    w = (cq.Workplane("XY").circle(40).extrude(6)
         .faces(">Z").workplane().polarArray(radius=30, startAngle=0, angle=360, count=6).hole(5))
    cq.exporters.export(w, str(step))
    geom = read_geometry(str(step))
    assert geom["ok"] is True
    out = recognize_features(geom)
    bcs = [p for p in out["patterns"] if p["type"] == "bolt_circle"]
    assert bcs and bcs[0]["count"] == 6
    assert abs(bcs[0]["pitch_circle_diameter"] - 60.0) < 0.5
