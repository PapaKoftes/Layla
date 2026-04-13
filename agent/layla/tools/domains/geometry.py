"""Structured geometry / CAD program tools (GenCAD-style command sequences)."""

TOOLS = {
    "geometry_validate_program": {
        "dangerous": False,
        "require_approval": False,
        "risk_level": "low",
        "category": "fabrication",
    },
    "geometry_execute_program": {
        "dangerous": True,
        "require_approval": True,
        "risk_level": "medium",
        "category": "fabrication",
    },
    "geometry_list_frameworks": {
        "dangerous": False,
        "require_approval": False,
        "risk_level": "low",
        "category": "fabrication",
    },
    "geometry_extract_machining_ir": {
        "dangerous": False,
        "require_approval": False,
        "risk_level": "low",
        "category": "fabrication",
    },
    "validate_fabrication_bundle": {
        "dangerous": False,
        "require_approval": False,
        "risk_level": "low",
        "category": "fabrication",
    },
    "gencad_generate_toolpath": {
        "dangerous": True,
        "require_approval": True,
        "risk_level": "medium",
        "category": "fabrication",
    },
}
