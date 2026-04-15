"""Authoritative Pydantic schema for file-backed structured plans (`.layla_plans/`)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

PlanStatus = Literal["draft", "approved", "executing", "paused", "done", "failed"]
StepStatus = Literal["pending", "ready", "blocked", "running", "done", "failed", "skipped"]
StepType = Literal["analysis", "planning", "refactor", "edit", "test", "build", "cad", "research"]


def _uid() -> str:
    return str(uuid.uuid4())


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=_uid)
    title: str = ""
    description: str = ""
    type: StepType = Field(default="analysis")
    depends_on: List[str] = Field(default_factory=list)
    status: StepStatus = Field(default="pending")
    tools: List[str] = Field(default_factory=list)
    tools_auto_filled: bool = Field(
        default=False,
        description="True if tools were injected by in-loop normalize; may fail when plan_governance_reject_auto_filled_tools is on.",
    )
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    retries: int = 0
    max_retries: int = 1
    approval_required: bool = True
    notes: List[str] = Field(default_factory=list)


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=_uid)
    goal: str = ""
    context: str = ""
    workspace_root: Optional[str] = None

    status: PlanStatus = Field(default="draft")
    steps: List[PlanStep] = Field(default_factory=list)

    created_at: str = Field(default_factory=_utc_iso)
    updated_at: str = Field(default_factory=_utc_iso)

    memory_summary: str = ""
    repo_map_summary: str = ""

    allow_run: bool = False
    allow_write: bool = False

    current_step_id: Optional[str] = None

    notes: List[str] = Field(default_factory=list)

    def next_ready_step(self) -> PlanStep | None:
        ready = self.all_ready_steps()
        return ready[0] if ready else None

    def all_ready_steps(self) -> List[PlanStep]:
        """All pending/ready steps whose dependencies are satisfied (topological wave)."""
        terminal_ok = frozenset({"done", "skipped"})
        done = {s.id for s in self.steps if s.status in terminal_ok}
        out: List[PlanStep] = []
        for s in self.steps:
            if s.status in ("pending", "ready"):
                deps = s.depends_on or []
                if all(d in done for d in deps):
                    out.append(s)
        return out
