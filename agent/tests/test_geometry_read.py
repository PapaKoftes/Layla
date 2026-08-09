"""Golden tests for the Phase-2 3D readers (geometry_read).

Generates real fixtures at runtime (a box STL via trimesh; a plate with two Ø6 holes STEP via
cadquery) and reads them back, asserting hand-computed geometry. Skips cleanly if the optional
geometry libs are not installed, mirroring how the repo treats them as optional.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.geometry.geometry_read import read_brep, read_geometry, read_mesh  # noqa: E402


def test_read_mesh_box_stl(tmp_path):
    trimesh = pytest.importorskip("trimesh")
    stl = tmp_path / "box.stl"
    trimesh.creation.box(extents=[20.0, 10.0, 5.0]).export(str(stl))

    r = read_mesh(str(stl))
    assert r["ok"] is True
    assert r["format"] == "stl"
    assert r["dims"] == [20.0, 10.0, 5.0]
    assert r["watertight"] is True
    assert r["printable"] is True
    assert abs(r["volume"] - 1000.0) < 1e-3   # 20*10*5
    assert r["triangles"] == 12               # a box = 12 triangles


def test_read_brep_plate_with_holes_step(tmp_path):
    cq = pytest.importorskip("cadquery")
    step = tmp_path / "plate.step"
    # 40 x 30 x 5 plate, centered; two through-holes Ø6 (r=3) at x=-10 and x=+10.
    w = (
        cq.Workplane("XY").box(40, 30, 5)
        .faces(">Z").workplane().pushPoints([(-10, 0), (10, 0)]).hole(6)
    )
    cq.exporters.export(w, str(step))

    r = read_brep(str(step))
    assert r["ok"] is True, r.get("error")
    assert r["format"] == "step"
    assert r["dims"] == [40.0, 30.0, 5.0]
    assert r["solids"] == 1
    assert r["cylindrical_faces"] == 2                 # the two bores
    assert len(r["holes"]) == 2
    assert all(abs(h["radius"] - 3.0) < 1e-3 for h in r["holes"])
    # 40*30*5 minus two Ø6 through-holes (pi*9*5 each) ~= 5717.3
    assert abs(r["volume"] - 5717.35) < 1.0


def test_read_geometry_dispatch_and_unsupported(tmp_path):
    pytest.importorskip("trimesh")
    import trimesh
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[4.0, 4.0, 4.0]).export(str(stl))

    g = read_geometry(str(stl))
    assert g["ok"] is True and g["dimension"] == "3d-mesh"

    bad = read_geometry(str(tmp_path / "whatever.xyz"))
    assert bad["ok"] is False and "unsupported" in bad["error"]
