"""
Static fabrication toolchain DAG hints (MVP). Pure functions for planner bias — no execution.

Complements services/toolchain_awareness.py policy nudges with step-order cost suggestions.
"""
from __future__ import annotations

from typing import Sequence

# Ordered ideal chain for DXF/2D → motion (tool names as registered)
_DEFAULT_CHAIN: tuple[str, ...] = (
    "geometry_extract_machining_ir",
    "generate_gcode",
    "validate_fabrication_bundle",
)

# Ordered ideal chain for code changes (read → understand → change → verify)
_CODE_CHAIN: tuple[str, ...] = (
    "read_file",
    "python_ast",
    "search_codebase",
    "apply_patch",
    "run_tests",
    "git_status",
    "git_diff",
)

# Ordered ideal chain for research (search → fetch → summarize → store)
_RESEARCH_CHAIN: tuple[str, ...] = (
    "ddg_search",
    "fetch_article",
    "summarize_text",
    "save_note",
)

# Ordered ideal chain for documentation edits (read → understand → write)
_DOCS_CHAIN: tuple[str, ...] = (
    "read_file",
    "understand_file",
    "write_file",
)


def _norm_step(name: str) -> str:
    return str(name or "").strip().lower().replace("-", "_")


def suggest_cheaper_path(steps_done: Sequence[str]) -> str:
    """
    If executed steps skip IR before G-code, suggest inserting machining IR extraction.
    """
    norm = [_norm_step(s) for s in steps_done if _norm_step(s)]
    if "generate_gcode" in norm and "geometry_extract_machining_ir" not in norm:
        return (
            "Toolchain: run geometry_extract_machining_ir before generate_gcode for DXF/vector "
            "sources to reduce rework and invalid motion."
        )
    if norm.count("generate_gcode") > 1:
        return "Toolchain: batch generate_gcode per stock/setup instead of repeating isolated posts."
    if "validate_fabrication_bundle" in norm and "geometry_extract_machining_ir" not in norm:
        return "Toolchain: validate_fabrication_bundle is stronger when paired with geometry_extract_machining_ir output."
    return ""


def planner_toolchain_cost_line(goal: str) -> str:
    """Single line for build_planning_bias_prompt when the goal looks fabrication-related."""
    g = (goal or "").lower()
    if any(k in g for k in ("implement", "fix", "refactor", "pytest", "bug", "code", "function", "class")):
        return f"Toolchain default order (heuristic): {' → '.join(_CODE_CHAIN)} — read/parse before patching; verify with tests/diff."
    if any(k in g for k in ("research", "paper", "arxiv", "citation", "source", "evidence")):
        return f"Toolchain default order (heuristic): {' → '.join(_RESEARCH_CHAIN)} — fetch primary sources before summarizing."
    if any(k in g for k in ("readme", "docs", "documentation", "changelog", "contributing")):
        return f"Toolchain default order (heuristic): {' → '.join(_DOCS_CHAIN)} — understand the file before editing."
    if not any(k in g for k in ("gcode", "g-code", "dxf", "machining", "cnc", "toolpath", "fabrication")):
        return ""
    tokens = []
    for raw in g.replace("`", " ").replace("/", " ").split():
        t = raw.strip(".,:;()[]\"'")
        if "_" in t and all(c.isalnum() or c == "_" for c in t):
            tokens.append(t)
    hint = suggest_cheaper_path(tokens)
    if hint:
        return hint
    return (
        f"Toolchain default order (heuristic): {' → '.join(_DEFAULT_CHAIN)} — adjust for your stock and machine."
    )


def deterministic_toolchain_route(goal: str) -> dict[str, object]:
    """
    Deterministically classify goals into a toolchain and allowed tool set.
    Returns: {route, chain, allowed_tools}
    """
    g = (goal or "").lower()
    if any(k in g for k in ("gcode", "g-code", "dxf", "machining", "cnc", "toolpath", "fabrication", "cam")):
        chain = list(_DEFAULT_CHAIN) + ["cam_build_machine_intent"]
        return {"route": "cam", "chain": chain, "allowed_tools": chain}
    if any(k in g for k in ("research", "paper", "arxiv", "citation", "source", "evidence")):
        return {"route": "research", "chain": list(_RESEARCH_CHAIN), "allowed_tools": list(_RESEARCH_CHAIN)}
    if any(k in g for k in ("readme", "docs", "documentation", "changelog", "contributing")):
        return {"route": "docs", "chain": list(_DOCS_CHAIN), "allowed_tools": list(_DOCS_CHAIN)}
    if any(k in g for k in ("implement", "fix", "refactor", "pytest", "bug", "code", "function", "class", ".py", ".ts", ".tsx")):
        return {"route": "code", "chain": list(_CODE_CHAIN), "allowed_tools": list(_CODE_CHAIN)}
    return {"route": "default", "chain": [], "allowed_tools": []}
