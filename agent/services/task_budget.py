"""
Task profile + budget envelope: composes with reasoning_classifier and PolicyCaps.
Deterministic given fixed inputs; no LLM calls.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any

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


@dataclass(frozen=True)
class TaskProfile:
    """Structured signals for one autonomous run (logging / allocation)."""

    base_reasoning: str  # none | light | deep (from classifier + upstream caps)
    complexity_score: float  # 0..1
    coding_likelihood: float  # 0..1
    length_bin: str  # short | medium | long
    research_mode: bool
    allow_write: bool
    allow_run: bool
    goal_hash: str  # stable id for logs only

    def to_trace_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BudgetEnvelope:
    """Effective caps for one run; consumed by agent_loop."""

    reasoning_mode_effective: str
    max_tool_calls_effective: int
    max_plan_depth_effective: int
    retrieval_depth: str  # minimal | normal | deep
    macro_planning_allowed: bool

    def to_trace_dict(self) -> dict[str, Any]:
        return asdict(self)


def _goal_fingerprint(goal: str) -> str:
    g = (goal or "").strip().encode("utf-8", errors="replace")
    return hashlib.sha256(g).hexdigest()[:16]


def _length_bin(goal: str, context: str) -> str:
    n = len((goal or "").strip()) + len((context or "").strip())
    if n < 80:
        return "short"
    if n < 350:
        return "medium"
    return "long"


def _complexity_and_coding(goal: str, context: str) -> tuple[float, float]:
    combined = f"{(goal or '').strip()}\n{(context or '').strip()}".strip()
    cl = combined.lower()
    score = 0.0
    if len(combined) > 500:
        score += 0.35
    elif len(combined) > 200:
        score += 0.2
    elif len(combined) > 80:
        score += 0.1
    if any(k in cl for k in _CODING_KW):
        score += 0.35
    if any(k in cl for k in _PLAN_KW):
        score += 0.15
    if _CODE_BLOCK.search(combined):
        score += 0.2
    if re.search(r"\b(todo|fixme|implement|refactor)\b", cl):
        score += 0.1
    coding = 0.25
    if any(k in cl for k in _CODING_KW) or _CODE_BLOCK.search(combined):
        coding = min(1.0, coding + 0.55)
    if ".py" in cl or ".ts" in cl or ".rs" in cl:
        coding = min(1.0, coding + 0.2)
    return max(0.0, min(1.0, score)), max(0.0, min(1.0, coding))


def profile_task(
    goal: str,
    context: str = "",
    *,
    reasoning_mode: str,
    research_mode: bool = False,
    allow_write: bool = False,
    allow_run: bool = False,
) -> TaskProfile:
    """
    Build a profile using the already-classified reasoning mode (caller runs classify + stabilize first).
    """
    br = (reasoning_mode or "light").strip().lower()
    if br not in ("none", "light", "deep"):
        br = "light"
    cx, cod = _complexity_and_coding(goal, context)
    return TaskProfile(
        base_reasoning=br,
        complexity_score=cx,
        coding_likelihood=cod,
        length_bin=_length_bin(goal, context),
        research_mode=bool(research_mode),
        allow_write=bool(allow_write),
        allow_run=bool(allow_run),
        goal_hash=_goal_fingerprint(goal),
    )


def allocate_budget(profile: TaskProfile, cfg: dict[str, Any] | None) -> BudgetEnvelope:
    """Map profile + config to effective caps."""
    c = cfg if isinstance(cfg, dict) else {}
    chat_lite = bool(c.get("chat_lite_mode"))
    base = profile.base_reasoning

    if profile.research_mode:
        mtc = max(1, int(c.get("research_max_tool_calls", 20)))
        mpd = max(1, int(c.get("max_plan_depth", 3)))
        return BudgetEnvelope(
            reasoning_mode_effective="deep",
            max_tool_calls_effective=mtc,
            max_plan_depth_effective=mpd,
            retrieval_depth="deep",
            macro_planning_allowed=not chat_lite,
        )

    cfg_mtc = max(1, int(c.get("max_tool_calls", 5)))
    cfg_mpd = max(0, int(c.get("max_plan_depth", 3)))

    if base == "none":
        return BudgetEnvelope(
            reasoning_mode_effective="none",
            max_tool_calls_effective=min(2, cfg_mtc),
            max_plan_depth_effective=0,
            retrieval_depth="minimal",
            macro_planning_allowed=False,
        )
    if base == "light":
        return BudgetEnvelope(
            reasoning_mode_effective="light",
            max_tool_calls_effective=min(5, cfg_mtc),
            max_plan_depth_effective=min(2, cfg_mpd) if cfg_mpd > 0 else 0,
            retrieval_depth="normal",
            macro_planning_allowed=not chat_lite and cfg_mpd > 0,
        )
    # deep
    return BudgetEnvelope(
        reasoning_mode_effective="deep",
        max_tool_calls_effective=cfg_mtc,
        max_plan_depth_effective=cfg_mpd,
        retrieval_depth="deep",
        macro_planning_allowed=not chat_lite and cfg_mpd > 0,
    )
