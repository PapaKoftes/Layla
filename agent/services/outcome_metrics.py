"""Pure helpers for post-run outcome metrics (latency, step counts, cost heuristic)."""
from __future__ import annotations

import time
from typing import Any


def collect_outcome_metrics(state: dict[str, Any]) -> dict[str, Any]:
    """Wall time from optional start_time; counts tool vs total steps."""
    steps = state.get("steps") or []
    tool_steps = [
        s
        for s in steps
        if s.get("action") and s["action"] not in ("reason", "think", "client_abort", "none")
    ]
    wall = 0.0
    st = state.get("start_time")
    if isinstance(st, (int, float)):
        wall = max(0.0, time.time() - float(st))
    return {
        "wall_time_seconds": round(wall, 3),
        "tool_step_count": len(tool_steps),
        "decision_steps": len(steps),
    }


def heuristic_cost_score(metrics: dict[str, Any], success: bool) -> float:
    """Higher is better: success weighted against time and tool churn."""
    t = float(metrics.get("wall_time_seconds") or 0.0)
    n = int(metrics.get("tool_step_count") or 0)
    denom = 1.0 + 0.05 * t + 0.02 * float(n)
    base = 1.0 if success else 0.2
    return round(base / denom, 4)
