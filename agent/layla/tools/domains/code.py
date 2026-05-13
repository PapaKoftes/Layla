"""Code search, execution, analysis, and refactoring tools."""

TOOLS = {
    "search_codebase": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "code",
        "description": "Semantic search across the codebase. Finds functions, classes, and patterns by meaning.",
    },
    "grep_code": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "code",
        "description": "Search files for a regex or literal pattern. Returns matching lines with context.",
    },
    "run_python": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "code",
        "description": "Execute a Python script or expression and return stdout, stderr, and exit code.",
    },
    "run_tests": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "code",
        "description": "Run the project's test suite (pytest). Returns pass/fail counts and failure details.",
    },
    "python_ast": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "code",
        "description": "Parse a Python file into its AST and return classes, functions, imports, and call graph.",
    },
    "project_discovery": {
        "fn_key": "project_discovery_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Auto-detect project type, language, framework, and entry points from workspace files.",
    },
    "security_scan": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Scan source code for common security issues: hardcoded secrets, SQL injection patterns, unsafe deserialization.",
    },
    "code_symbols": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Extract all symbols (functions, classes, variables) from a source file with line numbers.",
    },
    "find_todos": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Find all TODO, FIXME, HACK, and XXX comments across the codebase.",
    },
    "dependency_graph": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "code",
        "description": "Build an import dependency graph for a Python project. Shows which modules depend on which.",
    },
    "code_metrics": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Compute code metrics: lines of code, cyclomatic complexity, function lengths, and duplication.",
    },
    "code_lint": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Run linting checks (ruff/flake8) on source files and return warnings and errors.",
    },
    "rename_symbol": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "code",
        "description": "Rename a function, class, or variable across all files that reference it.",
    },
    "code_format": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "code",
        "description": "Auto-format source code using the project's configured formatter (black, ruff, prettier).",
    },
    "generate_gcode": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "fabrication",
        "description": "Generate G-code toolpaths from geometry definitions for CNC machining.",
    },
}
