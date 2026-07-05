"""Proactive goal tracking (BL-240) — turn the goals store into weeks-long momentum.

The goals / goal_progress tables already record long-term goals and progress notes. This
reads them as a *dashboard* — latest completion %, days since last movement, momentum —
and derives **proactive suggestions**: stalled goals to resume, near-done goals to finish,
fresh goals to break down. Those suggestions can feed the initiative engine so Layla nudges
progress over weeks instead of only reacting within a single turn.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("layla")

_STALE_DAYS = 7
_NEAR_DONE = 80.0


def _days_since(iso: str) -> float:
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _goal_view(goal: dict) -> dict[str, Any]:
    from layla.memory.user_profile import get_goal_progress
    history = get_goal_progress(goal["id"])
    pct = float(history[-1]["progress_pct"]) if history else 0.0
    last_note = history[-1]["note"] if history else ""
    idle = _days_since(goal.get("updated_at") or goal.get("created_at") or "")
    if pct >= 100:
        status = "complete"
    elif pct >= _NEAR_DONE:
        status = "near_done"
    elif idle >= _STALE_DAYS:
        status = "stalled"
    else:
        status = "on_track"
    return {
        "id": goal["id"],
        "title": goal.get("title", ""),
        "progress_pct": round(pct, 1),
        "updates": len(history),
        "days_idle": round(idle, 1),
        "last_note": last_note,
        "status": status,
    }


def goal_dashboard(project_id: str = "") -> dict[str, Any]:
    """Active goals with derived progress/momentum status."""
    from layla.memory.user_profile import get_active_goals
    goals = [_goal_view(g) for g in get_active_goals(project_id)]
    return {
        "goals": goals,
        "counts": {
            "total": len(goals),
            "stalled": sum(1 for g in goals if g["status"] == "stalled"),
            "near_done": sum(1 for g in goals if g["status"] == "near_done"),
            "on_track": sum(1 for g in goals if g["status"] == "on_track"),
        },
    }


def proactive_suggestions(project_id: str = "", *, stale_days: int = _STALE_DAYS) -> list[dict[str, Any]]:
    """Actionable nudges derived from goal state (stalled / near-done / needs-breakdown)."""
    suggestions: list[dict[str, Any]] = []
    for g in goal_dashboard(project_id)["goals"]:
        if g["status"] == "near_done":
            suggestions.append({
                "goal_id": g["id"], "title": g["title"], "kind": "finish",
                "suggestion": f"“{g['title']}” is {g['progress_pct']}% done — want to push it over the line?",
            })
        elif g["status"] == "stalled":
            suggestions.append({
                "goal_id": g["id"], "title": g["title"], "kind": "resume",
                "suggestion": f"“{g['title']}” hasn't moved in {int(g['days_idle'])} days — resume it?",
            })
        elif g["updates"] == 0:
            suggestions.append({
                "goal_id": g["id"], "title": g["title"], "kind": "breakdown",
                "suggestion": f"“{g['title']}” has no progress yet — shall I break it into first steps?",
            })
    return suggestions


def initiative_goal_hints(project_id: str = "", *, limit: int = 3) -> list[str]:
    """Compact hint strings the initiative engine can fold into its proactive nudges."""
    return [s["suggestion"] for s in proactive_suggestions(project_id)[:limit]]
