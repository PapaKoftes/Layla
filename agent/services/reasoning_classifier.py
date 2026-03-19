"""
Lightweight heuristic: how much planner / reflection depth does this turn need?
Returns 'none' | 'light' | 'deep'. No LLM calls.
"""
from __future__ import annotations

import re

_CODING_KW = (
    "def ", "class ", "import ", "function", "refactor", "debug", "bug", "fix ",
    "implement", "code", "error", "stack trace", "traceback", "pytest", "unittest",
    "typescript", "javascript", "python", "rust", "compile", "build ", "lint",
    "pull request", "commit", "git ", ".py", ".ts", ".js", ".rs", ".go", ".java",
)

_PLAN_KW = (
    "step by step", "multi-step", "roadmap", "plan ", "break down", "first then",
    "outline how", "architecture for",
)

_CODE_BLOCK = re.compile(r"```|^\s*(def |class |import )\w", re.MULTILINE)


def classify_reasoning_need(goal: str, context: str = "", *, research_mode: bool = False) -> str:
    """
    Returns 'none' | 'light' | 'deep'.

    - none: very short chat / yes-no / greetings without code signals
    - deep: coding, long or multi-step prompts, code-looking context, research missions
    - light: default
    """
    g = (goal or "").strip()
    c = (context or "").strip()
    combined = f"{g}\n{c}".strip()
    gl = g.lower()
    cl = combined.lower()

    if research_mode:
        return "deep"

    if len(combined) > 350:
        return "deep"

    if any(k in cl for k in _CODING_KW):
        return "deep"
    if any(k in cl for k in _PLAN_KW):
        return "deep"
    if _CODE_BLOCK.search(combined):
        return "deep"

    # Short conversational / factual — no code hints
    if len(g) < 40:
        if not g:
            return "light"
        # yes/no style
        yn = re.match(r"^(is|are|was|were|do|does|did|can|could|should|will|would|have|has)\s+", gl)
        if yn or g.endswith("?") and len(g) < 35:
            return "none"
        # greeting / chat
        if re.match(r"^(hi|hey|hello|thanks|thank you|ok|okay|yes|no|yep|nope)\b", gl):
            return "none"
        if len(g.split()) <= 3 and "?" not in g and not any(ch in g for ch in "{}[]();"):
            return "none"

    return "light"


def stabilize_reasoning_mode(prev: str, current: str) -> str:
    """Reduce flip-flop between turns: if we were deep and now classify light, stay light."""
    p = (prev or "").strip().lower()
    c = (current or "").strip().lower()
    if p == "deep" and c == "light":
        return "light"
    return current
