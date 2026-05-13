"""Structured geometry / CAD program tools (GenCAD-style command sequences)."""

TOOLS = {
    "geometry_validate_program": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "Validate a GenCAD geometry program for syntax errors and constraint violations.",
    },
    "geometry_execute_program": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "fabrication",
        "description": "Execute a GenCAD geometry program and return the resulting geometry data.",
    },
    "geometry_list_frameworks": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "List available geometry frameworks and their supported operations.",
    },
    "geometry_extract_machining_ir": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "Extract machining intermediate representation from a geometry program for CAM processing.",
    },
    "validate_fabrication_bundle": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "Validate a complete fabrication bundle: geometry, toolpaths, material settings, and machine config.",
    },
    "cam_feed_speed_hint": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "Suggest optimal feed rate and spindle speed for a given material and tool combination.",
    },
    "cam_estimate_time": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "Estimate machining time for a toolpath based on feed rates and tool changes.",
    },
    "cam_list_tool_types": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "List available CNC tool types with their geometry profiles and typical applications.",
    },
    "cam_build_machine_intent": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "Build a structured machine intent from natural language machining instructions.",
    },
    "gencad_generate_toolpath": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "fabrication",
        "description": "Generate CNC toolpaths from a GenCAD geometry program with configurable strategy.",
    },
}
