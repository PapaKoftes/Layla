"""Golden tests for the G-code SEMANTIC reader (machining_ir.parse_gcode_semantics).

Hand-computed expected values — deterministic, no model/CAM sim. Complements the structural
linter tests (validate_gcode_text). This proves Layla can READ a .nc, not just lint it.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.geometry.machining_ir import parse_gcode_semantics  # noqa: E402

# A 10x10 square profile at Z=-1, safe retracts, spindle on before the first cut.
SQUARE = """
G21
G90
M3 S12000
G0 Z5
G0 X0 Y0
G1 Z-1 F100
G1 X10 Y0 F300
G1 X10 Y10
G1 X0 Y10
G1 X0 Y0
G0 Z5
M5
M30
"""


def test_square_profile_semantics():
    r = parse_gcode_semantics(SQUARE)
    assert r["ok"] is True
    assert r["units"] == "mm"
    assert r["cut_moves"] == 5          # plunge + 4 sides
    assert r["cut_length"] == 46.0      # 6 (plunge Z5->-1) + 4*10
    assert r["rapid_moves"] == 3        # Z5, X0Y0 (no-op), Z5 retract
    assert r["bbox"] == [0.0, 0.0, -1.0, 10.0, 10.0, 5.0]
    assert r["z_levels"] == [-1.0]
    assert r["depth_passes"] == 1
    assert r["spindle_speeds"] == [12000.0]
    assert r["safety"]["spindle_on_before_cut"] is True
    assert r["safety"]["rapid_below_z0"] == 0   # the Z5 retract from -1 is safe (pure Z up)


# Dangerous: rapid plunge into stock, then rapid traverse while buried.
CRASH = """
G21 G90
M3 S8000
G0 Z-1
G0 X10 Y10
G1 X0 Y0 F200
G0 Z5
"""


def test_crash_risk_rapids_flagged():
    r = parse_gcode_semantics(CRASH)
    # Z-1 rapid plunge (1) + X10Y10 traverse at Z-1 (1) = 2; the final Z5 retract is safe.
    assert r["safety"]["rapid_below_z0"] == 2


# G3 CCW quarter arc, radius 10, from (10,0) to (0,10) about center (0,0): length = 10*pi/2.
ARC = """
G21 G90
G1 X10 Y0 F200
G3 X0 Y10 I-10 J0
"""


def test_arc_length_semantics():
    r = parse_gcode_semantics(ARC)
    assert r["cut_moves"] == 2
    # 10 (straight) + 15.708 (quarter arc) = 25.708
    assert abs(r["cut_length"] - 25.708) < 0.01
    assert r["bbox"][3] == 10.0 and r["bbox"][4] == 10.0  # X,Y max reach 10


def test_no_spindle_before_cut_is_flagged():
    prog = "G21 G90\nG1 Z-1 F100\nG1 X5 F200\n"   # cut with no M3 first
    r = parse_gcode_semantics(prog)
    assert r["safety"]["spindle_on_before_cut"] is False
    assert r["cut_moves"] == 2
