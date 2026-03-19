"""
Reflection engine: generate post-task reflections (what worked, what failed, what could be improved).
Stores reflections as learnings. Integrated with agent_loop._save_outcome_memory.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")


def generate_reflections(state: dict) -> dict[str, str]:
    """
    Generate structured reflections from agent run state.
    Returns {what_worked, what_failed, what_could_improve}.
    Uses heuristics when LLM unavailable; otherwise LLM for richer reflections.
    """
    steps = state.get("steps") or []
    tool_steps = [s for s in steps if s.get("action") and s["action"] != "reason"]
    objective = (state.get("objective") or state.get("original_goal") or "")[:300]
    status = state.get("status", "")

    what_worked: list[str] = []
    what_failed: list[str] = []
    what_could_improve: list[str] = []

    for s in tool_steps:
        action = s.get("action", "")
        result = s.get("result")
        ok = isinstance(result, dict) and result.get("ok", False)
        if ok:
            what_worked.append(f"{action} succeeded")
        else:
            err = (result.get("error", "") if isinstance(result, dict) else str(result))[:100]
            what_failed.append(f"{action}: {err or 'failed'}")

    if status == "finished" and tool_steps:
        what_worked.append("Task completed")
    elif status != "finished" and what_failed:
        what_could_improve.append("Consider retrying with different approach or tools")

    # Try LLM for richer reflections when available
    try:
        from services.llm_gateway import run_completion
        prompt = (
            f"Task: {objective}\n"
            f"Steps: {len(tool_steps)} tool calls. Worked: {', '.join(what_worked[:5])}. Failed: {', '.join(what_failed[:5])}.\n"
            "Output exactly 3 lines:\n"
            "What worked: <one short phrase>\n"
            "What failed: <one short phrase>\n"
            "What could improve: <one short phrase>\n"
        )
        out = run_completion(prompt, max_tokens=150, temperature=0.2, stream=False)
        if isinstance(out, dict):
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
            if text and len(text.strip()) > 20:
                lines = [ln.strip() for ln in text.strip().split("\n") if ":" in ln]
                for line in lines[:3]:
                    if "what worked" in line.lower():
                        what_worked = [line.split(":", 1)[-1].strip()[:200]]
                    elif "what failed" in line.lower():
                        what_failed = [line.split(":", 1)[-1].strip()[:200]]
                    elif "what could" in line.lower() or "improve" in line.lower():
                        what_could_improve = [line.split(":", 1)[-1].strip()[:200]]
    except Exception as e:
        logger.debug("reflection LLM skipped: %s", e)

    return {
        "what_worked": "; ".join(what_worked[:3]) if what_worked else "Completed",
        "what_failed": "; ".join(what_failed[:3]) if what_failed else "None",
        "what_could_improve": "; ".join(what_could_improve[:3]) if what_could_improve else "N/A",
    }


def store_reflections_as_learnings(reflections: dict[str, str], objective: str = "") -> None:
    """Persist reflections as learnings for future retrieval."""
    if not reflections:
        return
    try:
        from layla.memory.db import save_learning
        parts = []
        if reflections.get("what_worked"):
            parts.append(f"Worked: {reflections['what_worked']}")
        if reflections.get("what_failed"):
            parts.append(f"Failed: {reflections['what_failed']}")
        if reflections.get("what_could_improve"):
            parts.append(f"Improve: {reflections['what_could_improve']}")
        if parts:
            content = f"Reflection ({objective[:80]}): " + " | ".join(parts)
            save_learning(content=content[:500], kind="strategy", source="reflection_engine")
    except Exception as e:
        logger.debug("store reflections failed: %s", e)


def run_reflection(state: dict) -> dict[str, str] | None:
    """
    Generate and store reflections after task completion.
    Called from _save_outcome_memory. Returns reflections dict or None.
    """
    if state.get("status") != "finished":
        return None
    steps = state.get("steps") or []
    tool_steps = [s for s in steps if s.get("action") and s["action"] != "reason"]
    if not tool_steps:
        return None
    reflections = generate_reflections(state)
    store_reflections_as_learnings(reflections, state.get("objective", "")[:100])
    return reflections
