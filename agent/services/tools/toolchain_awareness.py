"""
Lightweight toolchain cost/risk hints for planning (North Star toolchain awareness).
Includes a small weighted DAG for policy hints (not full CAM modeling).
"""
from __future__ import annotations

from typing import Any

from services.decision_policy import PolicyCaps

# Step id -> (cost, risk) for operator-style reasoning in plans
TOOLCHAIN_DXF_TO_MACHINE: tuple[tuple[str, str, str], ...] = (
    ("dxf_parse", "low", "low"),
    ("machining_ir_extract", "low", "medium"),
    ("toolpath_order", "low", "medium"),
    ("cam_feeds_offsets", "high", "high"),
    ("gcode_post", "medium", "high"),
    ("machine_run", "high", "high"),
)

# Dependency edges: later stage depends on earlier (for ordering warnings)
TOOLCHAIN_EDGES: tuple[tuple[str, str, float], ...] = (
    ("dxf_parse", "machining_ir_extract", 1.0),
    ("machining_ir_extract", "toolpath_order", 1.0),
    ("toolpath_order", "cam_feeds_offsets", 2.0),
    ("cam_feeds_offsets", "gcode_post", 1.5),
    ("gcode_post", "machine_run", 3.0),
)


def toolchain_graph_summary() -> dict[str, Any]:
    nodes = [{"id": s[0], "cost": s[1], "risk": s[2]} for s in TOOLCHAIN_DXF_TO_MACHINE]
    edges = [{"from": a, "to": b, "weight": w} for a, b, w in TOOLCHAIN_EDGES]
    return {"nodes": nodes, "edges": edges}


def policy_hint_from_toolchain(goal: str) -> PolicyCaps:
    """If goal mentions fabrication without prior-stage language, nudge verify (policy)."""
    g = (goal or "").lower()
    fab_kw = ("dxf", "gcode", "g-code", "machining", "cnc", "mill", "geometry_extract_machining_ir", "generate_gcode")
    if not any(k in g for k in fab_kw):
        return PolicyCaps()
    if "geometry_extract" in g or "machining_ir" in g:
        return PolicyCaps(sources=["toolchain_graph"])
    return PolicyCaps(require_verify_before_mutate=True, sources=["toolchain_fabrication_goal"])


def toolchain_planning_hint() -> str:
    lines = [
        "Fabrication toolchain (heuristic cost/risk; use geometry_extract_machining_ir before G-code when starting from DXF):",
    ]
    try:
        g = toolchain_graph_summary()
        wsum = sum(e.get("weight", 0) for e in g.get("edges", []) if isinstance(e, dict))
        if wsum:
            lines.append(f"  (DAG edge weight sum ~{wsum:.1f} — higher means more staged dependencies.)")
    except Exception:
        pass
    for step, cost, risk in TOOLCHAIN_DXF_TO_MACHINE:
        lines.append(f"  - {step}: cost={cost}, risk={risk}")
    lines.append("High-risk stages need human or CAM verification; Layla does not model feeds/tools/stock.")
    return "\n".join(lines)
