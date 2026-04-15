"""Rule-based CAM helpers (feeds/speeds heuristics only — not production CAM)."""

from layla.cam.feeds_speeds import lookup_sfm
from layla.cam.simulator import estimate_rough_time_minutes, simulate_gcode
from layla.cam.tool_library import list_tool_types


def build_machine_intent(
    *,
    ir: dict | None = None,
    gcode_text: str = "",
    feeds_speeds: dict | None = None,
    ir_validation: dict | None = None,
    gcode_validation: dict | None = None,
    gcode_simulation: dict | None = None,
) -> dict:
    """Bundle a single machine-intent artifact for handoff and downstream tooling."""
    return {
        "ok": True,
        "ir": ir if isinstance(ir, dict) else None,
        "feeds_speeds": feeds_speeds if isinstance(feeds_speeds, dict) else None,
        "gcode": (gcode_text or "").strip(),
        "ir_validation": ir_validation if isinstance(ir_validation, dict) else None,
        "gcode_validation": gcode_validation if isinstance(gcode_validation, dict) else None,
        "gcode_simulation": gcode_simulation if isinstance(gcode_simulation, dict) else None,
        "disclaimer": "NOT_MACHINE_READY: interpretive bundle only; verify toolpaths in CAM/simulation before running on hardware.",
    }


__all__ = [
    "lookup_sfm",
    "estimate_rough_time_minutes",
    "simulate_gcode",
    "list_tool_types",
    "build_machine_intent",
]
