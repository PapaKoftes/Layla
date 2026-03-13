---
priority: core
domain: fabrication-geometry
aspect: morrigan
---

# Fabrication & Geometry Reference — Morrigan's Workshop

For the North Star use case: geometry → fabrication → machine intent. Understanding file formats, workflow chains, and how to translate between them.

---

## Geometry File Formats

### .3dm — Rhino 3D Model
- Binary format created by McNeel's Rhinoceros 3D
- Contains: surfaces, curves, meshes, point clouds, layers, materials, block instances
- NURBS-based (Non-Uniform Rational B-Splines) — mathematically precise curves/surfaces
- Read/write in Python: `rhino3dm` library (`pip install rhino3dm`)
```python
import rhino3dm
model = rhino3dm.File3dm.Read("model.3dm")
for obj in model.Objects:
    geom = obj.Geometry
    if isinstance(geom, rhino3dm.Mesh):
        print(f"Mesh: {len(geom.Vertices)} vertices, {len(geom.Faces)} faces")
    elif isinstance(geom, rhino3dm.Brep):
        print(f"Brep: {geom.Faces.Count} faces")
```

### .gh / .ghx — Grasshopper Definition
- Visual programming for Rhino (parametric geometry)
- .gh = binary, .ghx = XML (human-readable)
- Contains: component graph, parameter values, solution cache
- Automation: Rhino.Compute, Hops component, or direct RhinoCommon via scripting
- Structure: nodes have GUIDs, connections defined by source/target GUIDs and parameter indices

### .dxf — Drawing Exchange Format
- ASCII or binary interchange format (Autodesk)
- Universal — supported by nearly everything
- Key sections: HEADER (variables), CLASSES, TABLES (layers, linetypes, text styles), BLOCKS, ENTITIES (the actual geometry), OBJECTS
- Entities: LINE, CIRCLE, ARC, ELLIPSE, LWPOLYLINE, POLYLINE, SPLINE, HATCH, INSERT (block reference), TEXT, MTEXT
```python
import ezdxf
doc = ezdxf.readfile("drawing.dxf")
msp = doc.modelspace()
for entity in msp:
    if entity.dxftype() == "LINE":
        start, end = entity.dxf.start, entity.dxf.end
    elif entity.dxftype() == "LWPOLYLINE":
        points = list(entity.get_points())  # [(x,y,bulge,start_width,end_width)]
# Create DXF
doc = ezdxf.new("R2010")
msp = doc.modelspace()
msp.add_line((0,0), (100,0))
msp.add_circle((50,50), radius=25)
doc.saveas("output.dxf")
```

### .dwg — AutoCAD Drawing
- Proprietary binary format (Autodesk) — more common than DXF in industry
- Read with `ezdxf` (limited) or convert via ODA File Converter (free CLI) to DXF first
- LibreDWG is an open-source C library with Python bindings

### .step / .stp — STEP (ISO 10303)
- Standard for The Exchange of Product model data
- Industry standard for 3D solid models in manufacturing
- Contains: precise solid geometry (B-Rep), product structure, tolerances
- `python-occ` (PythonOCC) can read/write STEP via OpenCASCADE
- `cadquery` (`pip install cadquery`) provides Pythonic STEP/IGES I/O

### .stl — Stereolithography
- Mesh-only format for 3D printing
- ASCII or binary; binary preferred (smaller)
- No color, no hierarchy, no metadata — just triangles
```python
import numpy as np
# Binary STL structure: 80-byte header, uint32 triangle count, then triangles
# Each triangle: 12-byte normal + 3*(12-byte vertex) + 2-byte attribute

# With trimesh:
import trimesh
mesh = trimesh.load("model.stl")
mesh.vertices, mesh.faces, mesh.face_normals
mesh.export("output.stl")
mesh.is_watertight   # True if manifold (printable)
mesh.volume
```

### .obj — Wavefront Object
- Text format for 3D meshes with UV coordinates and materials
- v = vertex, vn = normal, vt = UV, f = face
- Material library in separate .mtl file
```python
import trimesh
mesh = trimesh.load("model.obj")
# or manually:
vertices, faces, normals = [], [], []
with open("model.obj") as f:
    for line in f:
        if line.startswith("v "): vertices.append(list(map(float, line.split()[1:])))
        elif line.startswith("f "): faces.append([int(x.split("/")[0])-1 for x in line.split()[1:]])
```

---

## CNC / Fabrication File Formats

### G-code (.nc, .gcode, .tap)
The universal language of CNC machines. A sequential list of commands for tool movement and machine state.

**Key G-codes:**
| Code | Meaning |
|------|---------|
| G00 | Rapid positioning (no cutting) |
| G01 | Linear interpolation (cutting, specify F feedrate) |
| G02 | Circular interpolation clockwise |
| G03 | Circular interpolation counter-clockwise |
| G17/18/19 | Select XY / XZ / YZ plane |
| G20/G21 | Inch / Millimeter mode |
| G28 | Return to home position |
| G40/41/42 | Tool radius compensation off / left / right |
| G43 | Tool length offset |
| G54-G59 | Work coordinate systems |
| G80 | Cancel canned cycle |
| G81-G89 | Canned cycles (drill, bore, tap) |
| G90/G91 | Absolute / Incremental positioning |
| G94/G95 | Feed per minute / Feed per revolution |

**Key M-codes:**
| Code | Meaning |
|------|---------|
| M00 | Program stop |
| M03/M04 | Spindle on CW / CCW (specify S for RPM) |
| M05 | Spindle stop |
| M06 | Tool change (specify T number) |
| M08/M09 | Coolant on / off |
| M30 | End program, rewind |

**G-code example:**
```gcode
G21           ; millimeter mode
G90           ; absolute positioning
G28 G91 Z0   ; home Z axis
T01 M06       ; tool change to tool 1
S12000 M03    ; spindle on at 12000 RPM
G00 X0 Y0    ; rapid to origin
G43 H01 Z5   ; tool length offset, position at Z5
G01 Z-2 F1000 ; plunge at 1000 mm/min
G01 X100 Y0 F3000  ; cut to X100 at 3000 mm/min
G02 X100 Y50 I0 J25  ; arc: clockwise, center at I0 J25 from current pos
G00 Z10      ; retract
M05          ; spindle off
M30          ; end program
```

**Python G-code parsing:**
```python
import re
GCODE_PATTERN = re.compile(r"([XYZIFJKSTM])(-?\d+\.?\d*)", re.IGNORECASE)

def parse_line(line: str) -> dict:
    line = line.split(";")[0].strip()  # remove comments
    if not line: return {}
    params = {}
    for m in GCODE_PATTERN.finditer(line):
        params[m.group(1).upper()] = float(m.group(2))
    return params
```

### .sbp — ShopBot
- ShopBot CNC router proprietary format
- Similar to G-code but different syntax
- Key commands: MH (Move Home), MX/MY/MZ (Move), JX/JY/JZ (Jog), MS (Move Speed), JS (Jog Speed)
- Variables: VD (Variable Define), VA (Variable Array)
- Readable as plain text; convert to standard G-code with CAM software

### .nc — Generic CNC
- Usually G-code with manufacturer-specific dialects
- FANUC dialect most common (Japanese CNC manufacturer)
- Heidenhain dialect used in European milling machines (different syntax: L for line, CC for arc center)

### .cix — Biesse CNC
- Biesse router format for woodworking CNC
- XML-based; contains operations, toolpaths, and machine parameters
- `BORITURES` = drilling operations, `ROUTAGES` = routing operations

### .mpr / .bpp — Homag / Weeke
- Homag Group formats for woodworking machining centers
- MPR = main program, BPP = back panel processing
- Proprietary; require Homag software to generate/edit properly

---

## Geometry → Fabrication Workflow

### The Chain
```
Design Intent
    ↓
Parametric Model (Grasshopper / parametric CAD)
    ↓ export
Geometry (.3dm / .step / .dxf)
    ↓ import into CAM
CAM Software (Fusion360 / RhinoCAM / Aspire / VCarve)
    ↓ toolpath generation + post-processor
G-code (.nc / .tap / .sbp)
    ↓
CNC Machine
    ↓
Physical Part
```

### Python automation of the chain

**DXF → G-code (2D flat cutting):**
```python
import ezdxf
# Extract polylines from DXF
doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()
cuts = []
for entity in msp.query("LWPOLYLINE"):
    if entity.dxf.layer == "CUT":
        cuts.append(list(entity.get_points("xy")))

# Generate G-code for each polyline
def polyline_to_gcode(points, depth=-5, feedrate=3000, safe_z=5):
    lines = ["G21 G90", f"G00 Z{safe_z}"]
    for path in points:
        x0, y0 = path[0]
        lines.append(f"G00 X{x0:.3f} Y{y0:.3f}")
        lines.append(f"G01 Z{depth} F1000")
        for x, y in path[1:]:
            lines.append(f"G01 X{x:.3f} Y{y:.3f} F{feedrate}")
        lines.append(f"G00 Z{safe_z}")
    lines.append("M30")
    return "\n".join(lines)
```

**STL mesh analysis (3D print prep):**
```python
import trimesh
mesh = trimesh.load("part.stl")
print(f"Volume: {mesh.volume:.2f} cm³")
print(f"Watertight: {mesh.is_watertight}")
print(f"Bounds: {mesh.bounds}")   # [[min_x,min_y,min_z],[max_x,max_y,max_z]]
if not mesh.is_watertight:
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_normals(mesh)
# Orient for printing (minimize support)
mesh.rezero()   # move to origin
```

---

## Key Python Libraries for Fabrication/Geometry

| Library | Use | Install |
|---------|-----|---------|
| `ezdxf` | DXF read/write | `pip install ezdxf` |
| `rhino3dm` | Rhino .3dm read/write (no Rhino needed) | `pip install rhino3dm` |
| `trimesh` | Mesh processing (STL/OBJ/GLTF) | `pip install trimesh` |
| `shapely` | 2D geometry operations | `pip install shapely` |
| `cadquery` | Parametric 3D CAD + STEP/IGES I/O | `pip install cadquery` |
| `svgpathtools` | SVG path parsing and manipulation | `pip install svgpathtools` |
| `numpy-stl` | Fast STL I/O | `pip install numpy-stl` |
| `pyocc-core` | OpenCASCADE Python bindings | conda or wheel |
| `geopandas` | Geospatial data (DXF overlaps) | `pip install geopandas` |

---

## NURBS — The Math Behind Precision Curves

NURBS (Non-Uniform Rational B-Splines) are the mathematical foundation of Rhino and most professional CAD.

- **Control points**: define the shape (don't necessarily lie on the curve)
- **Knot vector**: defines parameter spacing and continuity
- **Weights**: make it "rational" — allow exact conics (circles, ellipses)
- **Degree**: higher = smoother, more computationally expensive
  - Degree 1 = polyline
  - Degree 3 = most common for smooth curves (cubic)
  - Degree 5 = smoother continuity, used for automotive surfaces

**Why it matters for fabrication:** NURBS → mesh conversion introduces approximation error. Tolerance setting (`Mesh.MaxEdgeLength`, `DistanceTolerance`) controls how close the mesh approximates the original. For CNC, tight tolerances matter.

---

## Coordinate Systems and Transforms

```python
import numpy as np

# 4x4 homogeneous transform matrix
def translation(tx, ty, tz):
    return np.array([
        [1, 0, 0, tx],
        [0, 1, 0, ty],
        [0, 0, 1, tz],
        [0, 0, 0,  1],
    ], dtype=float)

def rotation_z(angle_deg):
    a = np.radians(angle_deg)
    return np.array([
        [np.cos(a), -np.sin(a), 0, 0],
        [np.sin(a),  np.cos(a), 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ])

# Apply transform to points
def transform_points(pts: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """pts: (N, 3) array → homogeneous → transform → dehomogenize"""
    ones = np.ones((len(pts), 1))
    homo = np.hstack([pts, ones])        # (N, 4)
    transformed = (matrix @ homo.T).T    # (N, 4)
    return transformed[:, :3]            # (N, 3)
```
