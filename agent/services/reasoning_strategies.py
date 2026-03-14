"""
Multi-strategy reasoning: allow the agent to try multiple reasoning strategies and compare results.
Provides strategy hints for different problem types.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

REASONING_STRATEGIES = {
    "decomposition": "Break the problem into smaller subproblems. Solve each, then combine.",
    "analogy": "Find a similar problem you've solved. Adapt the approach.",
    "working_backwards": "Start from the desired outcome. What must be true just before?",
    "constraint_relaxation": "Temporarily ignore a constraint. Solve, then reintroduce it.",
    "exhaustive_small": "For small cases, enumerate and verify. Look for patterns.",
    "divide_conquer": "Split input in half. Solve recursively. Merge results.",
}


def get_strategy_for_task(goal: str) -> list[str]:
    """
    Suggest reasoning strategies based on task keywords.
    Returns list of strategy names (and optionally descriptions).
    """
    g = (goal or "").lower()
    suggested: list[str] = []
    if any(k in g for k in ("debug", "fix", "error", "trace", "bug")):
        suggested.extend(["decomposition", "working_backwards"])
    if any(k in g for k in ("implement", "build", "create", "refactor")):
        suggested.extend(["decomposition", "analogy"])
    if any(k in g for k in ("analyze", "understand", "explain")):
        suggested.extend(["decomposition", "exhaustive_small"])
    if any(k in g for k in ("optimize", "improve", "performance")):
        suggested.extend(["constraint_relaxation", "divide_conquer"])
    if not suggested:
        suggested = ["decomposition", "analogy"]
    # Deduplicate preserving order
    seen = set()
    out = []
    for s in suggested:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:3]


def get_strategy_prompt_hint(goal: str) -> str:
    """
    Return a prompt hint string with suggested reasoning strategies.
    Injected into agent context when useful.
    """
    strategies = get_strategy_for_task(goal)
    if not strategies:
        return ""
    parts = []
    for name in strategies:
        desc = REASONING_STRATEGIES.get(name, "")
        if desc:
            parts.append(f"- {name}: {desc}")
    if not parts:
        return ""
    return "Reasoning strategies to consider:\n" + "\n".join(parts)


def try_strategies(goal: str, strategies: list[str] | None = None) -> dict[str, Any]:
    """
    Placeholder for multi-strategy execution.
    In full implementation, would run LLM with each strategy and compare.
    For now, returns strategy hints for the main agent to use.
    """
    strat = strategies or get_strategy_for_task(goal)
    return {
        "suggested_strategies": strat,
        "hint": get_strategy_prompt_hint(goal),
    }
