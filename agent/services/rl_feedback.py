"""
Lightweight preference-learning feedback loop.

Uses tool_outcomes (success/failure rates, latency) and learning usefulness_scores
to build a preference signal that guides the planner and tool selection.

No external ML dependency — pure Python statistical learning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("layla.rl_feedback")


@dataclass
class ToolPreference:
    score: float
    success_rate: float
    avg_latency_ms: float
    usefulness: float
    sample_count: int


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_tool_preferences(db_path: str | None = None) -> dict[str, ToolPreference]:
    """
    Query tool_outcomes and capability_events to build preference scores per tool.

    preference_score = success_rate * 0.6 + (1 - clamp(avg_latency_ms/5000, 0, 1)) * 0.2
                       + avg_usefulness * 0.2
    """
    try:
        from layla.memory.db import get_tool_reliability
        reliability = get_tool_reliability()
    except Exception as e:
        logger.debug("compute_tool_preferences: get_tool_reliability failed: %s", e)
        reliability = {}

    # Query capability_events for usefulness per "tool" domain
    # capability_events.domain_id is used as a proxy for tool identity when notes contains tool name
    usefulness_by_tool: dict[str, list[float]] = {}
    try:
        from layla.memory.db import _conn, migrate  # type: ignore[attr-defined]
        migrate()
        with _conn() as db:
            rows = db.execute(
                "SELECT notes, usefulness_score FROM capability_events WHERE notes != '' AND usefulness_score IS NOT NULL"
            ).fetchall()
        for row in rows:
            notes = (row["notes"] or "").strip()
            # notes field may be prefixed with "tool:<name>" or just contain the tool name
            tool_name = None
            if notes.startswith("tool:"):
                tool_name = notes[5:].split()[0].strip()
            elif notes.startswith("rl:"):
                tool_name = notes[3:].split()[0].strip()
            if tool_name:
                usefulness_by_tool.setdefault(tool_name, []).append(float(row["usefulness_score"]))
    except Exception as e:
        logger.debug("compute_tool_preferences: capability_events query failed: %s", e)

    result: dict[str, ToolPreference] = {}
    all_tools = set(reliability.keys()) | set(usefulness_by_tool.keys())

    for tool_name in all_tools:
        stats = reliability.get(tool_name, {})
        success_rate = float(stats.get("success_rate", 0.5))
        avg_latency_ms = float(stats.get("avg_latency", 0.0))
        sample_count = int(stats.get("count", 0))

        usefulness_scores = usefulness_by_tool.get(tool_name, [])
        avg_usefulness = sum(usefulness_scores) / len(usefulness_scores) if usefulness_scores else 0.5

        latency_factor = 1.0 - _clamp(avg_latency_ms / 5000.0, 0.0, 1.0)
        score = success_rate * 0.6 + latency_factor * 0.2 + avg_usefulness * 0.2

        result[tool_name] = ToolPreference(
            score=round(score, 4),
            success_rate=round(success_rate, 4),
            avg_latency_ms=round(avg_latency_ms, 2),
            usefulness=round(avg_usefulness, 4),
            sample_count=sample_count,
        )

    return result


def update_tool_preference_hints(prefs: dict[str, ToolPreference]) -> dict[str, str]:
    """
    Returns {tool_name: hint} where hint is one of:
      "preferred"   — score > 0.8 and sample_count >= 5
      "avoid"       — score < 0.3 and sample_count >= 5
      "unreliable"  — success_rate < 0.5 and sample_count >= 3
      ""            — no hint
    """
    hints: dict[str, str] = {}
    for tool_name, pref in prefs.items():
        if pref.score > 0.8 and pref.sample_count >= 5:
            hints[tool_name] = "preferred"
        elif pref.score < 0.3 and pref.sample_count >= 5:
            hints[tool_name] = "avoid"
        elif pref.success_rate < 0.5 and pref.sample_count >= 3:
            hints[tool_name] = "unreliable"
        else:
            hints[tool_name] = ""
    return hints


def get_rl_hint_for_prompt(db_path: str | None = None) -> str:
    """
    Returns a formatted string for injection into the system prompt.
    Returns empty string if no data or all hints are empty.
    """
    try:
        prefs = compute_tool_preferences(db_path)
        if not prefs:
            return ""
        hints = update_tool_preference_hints(prefs)

        preferred = [t for t, h in hints.items() if h == "preferred"]
        avoid = [t for t, h in hints.items() if h == "avoid"]
        unreliable = [t for t, h in hints.items() if h == "unreliable"]

        if not preferred and not avoid and not unreliable:
            return ""

        lines = ["## Tool Performance Hints (from past experience)"]
        lines.append(f"Prefer: {', '.join(preferred) if preferred else 'none'}")
        lines.append(f"Avoid: {', '.join(avoid) if avoid else 'none'}")
        lines.append(f"Unreliable: {', '.join(unreliable) if unreliable else 'none'}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("get_rl_hint_for_prompt failed: %s", e)
        return ""


def record_outcome_feedback(
    tool_name: str,
    success: bool,
    latency_ms: float = 0.0,
    usefulness_score: Optional[float] = None,
    db_path: str | None = None,
) -> None:
    """
    Write path: record tool outcome in tool_outcomes table.
    If usefulness_score provided, also add a capability_event.
    """
    if not tool_name:
        return
    try:
        from layla.memory.db import record_tool_outcome
        record_tool_outcome(tool_name, success=success, latency_ms=latency_ms)
    except Exception as e:
        logger.debug("record_outcome_feedback: record_tool_outcome failed: %s", e)

    if usefulness_score is not None:
        try:
            from layla.memory.db import add_capability_event
            add_capability_event(
                domain_id="self_maintenance",
                event_type="tool_feedback",
                notes=f"rl:{tool_name}",
                usefulness_score=float(usefulness_score),
            )
        except Exception as e:
            logger.debug("record_outcome_feedback: add_capability_event failed: %s", e)


def run_preference_update_job() -> None:
    """
    Called by scheduler every 30 minutes.
    Computes preferences, stores summary in rl_preferences SQLite table.
    """
    try:
        from layla.memory.db import _conn, migrate, upsert_rl_preference  # type: ignore[attr-defined]
        migrate()

        prefs = compute_tool_preferences()
        hints = update_tool_preference_hints(prefs)

        n_preferred = sum(1 for h in hints.values() if h == "preferred")
        n_avoided = sum(1 for h in hints.values() if h == "avoid")

        for tool_name, pref in prefs.items():
            hint = hints.get(tool_name, "")
            try:
                upsert_rl_preference(tool_name, pref.score, hint)
            except Exception as e:
                logger.debug("run_preference_update_job: upsert failed for %s: %s", tool_name, e)

        logger.info(
            "RL preference update: %d tools tracked, %d preferred, %d avoided",
            len(prefs),
            n_preferred,
            n_avoided,
        )
    except Exception as e:
        logger.warning("run_preference_update_job failed: %s", e)
