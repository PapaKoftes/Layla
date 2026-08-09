"""
Phase 2 (North Star 4/5/17): READ real 3D geometry, not just recognize the extension.

- Mesh (.stl/.obj/.ply/.off): trimesh, in-process (pure-Python-safe).
- B-rep (.step/.stp/.iges/.igs): cadquery/OCP in a SUBPROCESS -- OCC can hard-crash on bad
  input, so we isolate it (same pattern as backends/cadquery_backend.py). Recognizes cylindrical
  faces as hole candidates (radius/axis/center), plus bbox/volume/solid/face counts.
- read_geometry(path): dispatcher that also routes .dxf to the existing 2D machining IR.

All readers degrade gracefully ({"ok": False, "error": ...}) if a lib is missing or a file is
bad -- nothing here raises. Deterministic; NOT a CAM/collision certifier.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

_MESH_EXT = {".stl", ".obj", ".ply", ".off"}
_BREP_EXT = {".step", ".stp", ".iges", ".igs"}


def read_mesh(path: str) -> dict[str, Any]:
    """Mesh summary via trimesh (bbox, volume, watertight/printable). In-process, safe."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": "file not found"}
    try:
        import trimesh
    except ImportError:
        return {"ok": False, "error": "trimesh not installed (pip install trimesh)"}
    try:
        m = trimesh.load(str(p), force="mesh")
    except Exception as e:  # noqa: BLE001 - readers never raise
        return {"ok": False, "error": f"mesh load failed: {e}"}
    if m is None or getattr(m, "bounds", None) is None or len(getattr(m, "faces", [])) == 0:
        return {"ok": False, "error": "no mesh geometry parsed"}
    lo, hi = m.bounds
    watertight = bool(m.is_watertight)
    return {
        "ok": True,
        "format": p.suffix.lstrip(".").lower(),
        "bbox": [round(float(v), 4) for v in (*lo, *hi)],
        "dims": [round(float(hi[i] - lo[i]), 4) for i in range(3)],
        "volume": round(float(m.volume), 4) if watertight else None,
        "area": round(float(m.area), 4),
        "triangles": int(len(m.faces)),
        "watertight": watertight,
        "winding_consistent": bool(m.is_winding_consistent),
        "printable": bool(watertight and m.is_winding_consistent),
    }


_BREP_READER = r'''
import sys, json
from pathlib import Path
path = sys.argv[1]
ext = Path(path).suffix.lower()
try:
    import cadquery as cq
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
except Exception as e:
    print(json.dumps({"ok": False, "error": "cadquery/OCP unavailable: %s" % e})); sys.exit(0)
try:
    if ext in (".step", ".stp"):
        shape = cq.importers.importStep(path).val()
    else:
        from OCP.IGESControl import IGESControl_Reader
        r = IGESControl_Reader(); r.ReadFile(path); r.TransferRoots()
        shape = cq.Shape(r.OneShape())
    tds = shape.wrapped
    bb = Bnd_Box(); BRepBndLib.Add_s(tds, bb)
    xmin, ymin, zmin, xmax, ymax, zmax = bb.Get()
    props = GProp_GProps(); BRepGProp.VolumeProperties_s(tds, props); vol = props.Mass()
    holes = []; n_plane = 0
    faces = shape.Faces()
    for f in faces:
        s = BRepAdaptor_Surface(f.wrapped)
        t = s.GetType()
        if t == GeomAbs_Cylinder:
            cyl = s.Cylinder(); ax = cyl.Axis(); loc = ax.Location(); d = ax.Direction()
            holes.append({"radius": round(cyl.Radius(), 4),
                          "axis_dir": [round(d.X(), 4), round(d.Y(), 4), round(d.Z(), 4)],
                          "center": [round(loc.X(), 4), round(loc.Y(), 4), round(loc.Z(), 4)]})
        elif t == GeomAbs_Plane:
            n_plane += 1
    print(json.dumps({
        "ok": True, "format": ext.lstrip("."),
        "bbox": [round(v, 4) for v in (xmin, ymin, zmin, xmax, ymax, zmax)],
        "dims": [round(xmax - xmin, 4), round(ymax - ymin, 4), round(zmax - zmin, 4)],
        "volume": round(vol, 4),
        "solids": len(shape.Solids()), "faces": len(faces),
        "planar_faces": n_plane, "cylindrical_faces": len(holes),
        "holes": holes,
    }))
except Exception as e:
    print(json.dumps({"ok": False, "error": "brep parse failed: %s" % e})); sys.exit(0)
'''


def read_brep(path: str, timeout: float = 120.0) -> dict[str, Any]:
    """B-rep (STEP/IGES) summary + cylindrical hole candidates. Runs OCC in a subprocess so an
    OCC crash on malformed input cannot take down the caller (mirrors cadquery_backend.py)."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": "file not found"}
    try:
        r = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(_BREP_READER), str(p)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "brep reader subprocess timeout"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    out = (r.stdout or "").strip()
    if not out:
        return {"ok": False, "error": (r.stderr or "brep reader produced no output")[:500]}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": f"unparseable reader output: {out[:300]}"}


def read_geometry(path: str) -> dict[str, Any]:
    """Dispatch by extension to the right reader. Adds a `dimension` tag. .dxf reuses the 2D
    machining IR; mesh/B-rep use the readers above; unknown extensions return ok=False."""
    ext = Path(path).suffix.lower()
    if ext == ".dxf":
        from layla.geometry.machining_ir import build_machining_ir
        ir = build_machining_ir(path)
        ir["dimension"] = "2d"
        return ir
    if ext in _MESH_EXT:
        out = read_mesh(path)
        out["dimension"] = "3d-mesh"
        return out
    if ext in _BREP_EXT:
        out = read_brep(path)
        out["dimension"] = "3d-brep"
        return out
    return {"ok": False, "error": f"unsupported geometry format: {ext or '(none)'}"}
