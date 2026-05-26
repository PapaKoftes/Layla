"""
Experience replay: periodically review past tool outcomes and reflections to improve planning heuristics.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def get_recent_tool_patterns(n: int = 50) -> list[dict[str, Any]]:
    """Extract patterns from recent tool outcomes: which tools succeed/fail in what contexts."""
    try:
        from layla.memory.db import get_tool_reliability
        stats = get_tool_reliability()
        patterns = []
        for tool, s in stats.items():
            if s.get("count", 0) >= 3:
                patterns.append({
                    "tool": tool,
                    "success_rate": s.get("success_rate", 0),
                    "avg_latency": s.get("avg_latency", 0),
                    "count": s.get("count", 0),
                })
        patterns.sort(key=lambda x: -x["count"])
        return patterns[:n]
    except Exception as e:
        logger.debug("get_recent_tool_patterns failed: %s", e)
        return []


def get_recent_reflections(n: int = 10) -> list[str]:
    """Get recent reflection learnings (strategy type from reflection_engine)."""
    try:
        from layla.memory.db import get_recent_learnings
        learnings = get_recent_learnings(n=n * 3)  # fetch more, filter
        reflections = []
        for L in learnings:
            c = (L.get("content") or "").strip()
            if "Reflection" in c or "Worked:" in c or "Failed:" in c or "Improve:" in c:
                reflections.append(c[:200])
        return reflections[:n]
    except Exception as e:
        logger.debug("get_recent_reflections failed: %s", e)
        return []


def get_reliable_tools(min_success_rate: float = 0.8, min_count: int = 3) -> list[str]:
    """Return tool names that have high reliability based on past outcomes. Used by planner."""
    patterns = get_recent_tool_patterns(50)
    return [
        p["tool"] for p in patterns
        if p.get("success_rate", 0) >= min_success_rate and p.get("count", 0) >= min_count
    ][:10]


def run_experience_replay() -> dict[str, Any]:
    """
    Review past outcomes and reflections. Update planning heuristics.
    Called periodically (scheduler) or after many tool runs.
    Returns summary of patterns found.
    """
    patterns = get_recent_tool_patterns(20)
    reflections = get_recent_reflections(5)
    # Heuristics could be stored in style_profile or a dedicated table
    # For now we just expose patterns; planner already uses get_tool_reliability
    return {
        "tool_patterns": len(patterns),
        "reflections_reviewed": len(reflections),
        "top_reliable_tools": [p["tool"] for p in patterns if p.get("success_rate", 0) >= 0.8][:5],
    }
