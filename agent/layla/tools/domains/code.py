"""Code search, execution, analysis, and refactoring tools."""

TOOLS = {
    "grep_code": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "run_python": {"dangerous": True, "require_approval": True, "risk_level": "high"},
    "run_tests": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "python_ast": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "project_discovery": {"fn_key": "project_discovery_tool", "dangerous": False, "require_approval": False, "risk_level": "low"},
    "security_scan": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "code_symbols": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "find_todos": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "dependency_graph": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "code_metrics": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "code_lint": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "rename_symbol": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "code_format": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "generate_gcode": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
}
