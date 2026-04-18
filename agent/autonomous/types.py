from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DecisionType = Literal["tool", "final"]


@dataclass(frozen=True)
class AutonomousTask:
    goal: str
    workspace_root: str
    max_steps: int = 50
    timeout_seconds: int = 60
    confirm_autonomous: bool = False
    allow_write: bool = False  # wiki writes only (no other mutations)
    allow_network: bool = False
    research_mode: bool = False


@dataclass(frozen=True)
class PlannerDecision:
    type: DecisionType
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    final: dict[str, Any] = field(default_factory=dict)
    attempts_used: int = 1  # LLM parse attempts for this decide() call (1 or 2)


@dataclass
class StepRecord:
    i: int
    decision: PlannerDecision
    tool_ok: bool = False
    tool_result: dict[str, Any] | None = None
    error: str | None = None

