from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValueGateResult:
    ok: bool
    reason: str
    score: int


_TRIVIAL_PREFIXES = (
    "hi",
    "hello",
    "thanks",
    "thank you",
    "ok",
    "k",
)

# Obvious direct-action / execution phrasing (use POST /agent instead).
_DIRECT_ACTION_PATTERNS = (
    r"\bwrite\s+(a\s+)?file",
    r"\bcreate\s+(a\s+)?file",
    r"\bdelete\s+",
    r"\brun\s+",
    r"\bexecute\s+",
    r"\bapply\s+patch",
    r"\bgit\s+push",
    r"\bpip\s+install",
    r"\bshell\b",
    r"\bfix\s+the\s+code",
    r"\bimplement\s+",
    r"\badd\s+a\s+feature",
)

# Short goals that still clearly signal investigation (avoid blocking "trace X" style asks).
_INVESTIGATION_BOOST = (
    "investigate",
    "investigation",
    "analyze",
    "analysis",
    "debug",
    "trace",
    "audit",
    "explore",
    "why ",
    "how does",
    "compare",
    "root cause",
    "bug",
    "issue",
    "grep",
    "search",
    "survey",
    "map ",
)


def evaluate_value_gate(goal: str, *, context: str = "") -> ValueGateResult:
    """
    Deterministic heuristic gate.

    Autonomous tier-0 is for **investigation / analysis** only — not direct execution.
    Reject trivial chat, one-liners, and obvious "do this for me" edits.
    """
    g = (goal or "").strip().lower()
    c = (context or "").strip().lower()
    if not g:
        return ValueGateResult(ok=False, reason="empty_goal", score=0)
    if len(g) <= 12 and any(g == p or g.startswith(p + " ") for p in _TRIVIAL_PREFIXES):
        return ValueGateResult(ok=False, reason="trivial_greeting", score=0)

    # Single-clause direct action without investigation framing.
    for pat in _DIRECT_ACTION_PATTERNS:
        if re.search(pat, g, re.I):
            return ValueGateResult(ok=False, reason="direct_action_use_agent", score=0)

    # Very short requests are usually single-step (use /agent).
    if len(g) < 35 and not any(k in g for k in _INVESTIGATION_BOOST):
        return ValueGateResult(ok=False, reason="simple_task_use_agent", score=0)

    score = 0
    if len(g) >= 120:
        score += 2
    if any(k in g for k in ("audit", "explore", "map", "architecture", "regression", "history", "survey", "trace", "root cause")):
        score += 2
    if any(k in g for k in ("repo", "codebase", "project", "workflows", "ci", "release", "docs")):
        score += 2
    if any(k in g for k in ("find all", "everywhere", "across", "multiple files", "search for")):
        score += 2
    if any(k in g for k in ("investigate", "analyze", "analysis", "debug", "why ", "how does", "compare", "bug", "issue")):
        score += 2
    if context and len(c) > 400:
        score += 1

    if score >= 3:
        return ValueGateResult(ok=True, reason="high_leverage", score=score)
    return ValueGateResult(ok=False, reason="low_leverage_use_agent", score=score)
