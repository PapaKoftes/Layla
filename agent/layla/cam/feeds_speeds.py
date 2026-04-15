"""Conservative hobby-scale SFM/chipload heuristics (not machine-specific)."""

from __future__ import annotations


def lookup_sfm(material: str, tool_diameter_mm: float = 3.0) -> dict[str, object]:
    m = (material or "").lower().strip()
    d = max(0.1, float(tool_diameter_mm or 3.0))
    if any(x in m for x in ("alum", "aluminum", "6061", "7075")):
        return {
            "material_class": "non-ferrous",
            "sfm_range_fpm": (200, 450),
            "chipload_mm_per_tooth_nominal": round(0.02 + 0.01 * (d / 6.0), 4),
            "note": "Conservative nominal for hobby spindle; verify manufacturer charts.",
        }
    if any(x in m for x in ("steel", "stainless", "4140")):
        return {
            "material_class": "ferrous",
            "sfm_range_fpm": (80, 200),
            "chipload_mm_per_tooth_nominal": round(0.015 + 0.005 * (d / 6.0), 4),
            "note": "Use coolant/flood if available; slower for stainless.",
        }
    if any(x in m for x in ("wood", "plywood", "mdf", "plastic", "acrylic")):
        return {
            "material_class": "soft",
            "sfm_range_fpm": (600, 1200),
            "chipload_mm_per_tooth_nominal": round(0.05 + 0.02 * (d / 6.0), 4),
            "note": "Watch melting on plastics; dust collection for MDF.",
        }
    return {
        "material_class": "unknown",
        "sfm_range_fpm": (150, 400),
        "chipload_mm_per_tooth_nominal": round(0.03, 4),
        "note": "Default guess — confirm with tooling data and machine limits.",
    }
