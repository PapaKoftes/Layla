"""
Typed agent execution state (mutable, dict-compatible).

The main loop uses plain dict access (state["key"]). ExecutionState subclasses dict so all
existing code works while giving a single factory and serialization helpers.
"""
from __future__ import annotations

import time
import uuid
from typing import Any


class ExecutionState(dict):
    """
    Per-run agent state. Behaves as a dict; adds factory + JSON-safe export.

    Non-JSON-serializable values (e.g. sets) are stripped or converted in to_persistable_dict().
    """

    __slots__ = ()  # dict has no extra instance attrs

    @classmethod
    def create_initial(
        cls,
        *,
        goal: str,
        sub_goals: list[Any],
        active_aspect: dict[str, Any],
        memory_influenced: list[str],
        reasoning_mode: str,
        last_reasoning_mode: str,
        persona_focus_id: str,
        conversation_id: str,
        active_plan_id: str,
        plan_approved: bool,
        steps_container: list[Any],
        execution_id: str | None = None,
    ) -> ExecutionState:
        eid = (execution_id or "").strip() or str(uuid.uuid4())
        return cls(
            {
                "execution_id": eid,
                "goal": goal,
                "original_goal": goal,
                "objective": goal,
                "objective_complete": False,
                "depth": 0,
                "steps": steps_container,
                "status": "running",
                "start_time": time.time(),
                "tool_calls": 0,
                "aspect": active_aspect.get("id", "layla"),
                "aspect_name": active_aspect.get("name", "Layla"),
                "refused": False,
                "refusal_reason": "",
                "last_verification": None,
                "consecutive_no_progress": 0,
                "environment_aligned": None,
                "last_tool_used": None,
                "strategy_shift_count": 0,
                "priority_level": None,
                "impact_estimate": None,
                "effort_estimate": None,
                "risk_estimate": None,
                "ux_states": [],
                "memory_influenced": memory_influenced,
                "cited_knowledge_sources": [],
                "sub_goals": sub_goals,
                "reflection_pending": False,
                "reflection_asked": False,
                "last_reasoning_mode": last_reasoning_mode,
                "reasoning_mode": reasoning_mode,
                "_recent_exact_calls": set(),
                "persona_focus_for_stream": persona_focus_id,
                "conversation_id": conversation_id,
                "_think_seq": 0,
                "active_plan_id": (active_plan_id or "").strip(),
                "plan_approved": bool(plan_approved),
                # Plan / graph placeholders (coordinator + task graph)
                "plan": None,
                "current_step": "",
                "pipeline_stage": "EXECUTE",
                "tool_attempted_this_turn": False,
                "errors": [],
                "results": [],
                "retries": 0,
                "tools_used": [],
                "memory_hits": [],
            }
        )

    def to_persistable_dict(self) -> dict[str, Any]:
        """Strip non-JSON types for DB / API snapshots."""
        out: dict[str, Any] = {}
        for k, v in self.items():
            if k == "_recent_exact_calls" and isinstance(v, set):
                out[k] = list(v)
            elif isinstance(v, set):
                out[k] = list(v)
            else:
                try:
                    import json as _json

                    _json.dumps(v, default=str)
                    out[k] = v
                except TypeError:
                    out[k] = str(v)
        return out

    @classmethod
    def from_persistable_dict(cls, data: dict[str, Any]) -> ExecutionState:
        d = dict(data)
        if "_recent_exact_calls" in d and isinstance(d["_recent_exact_calls"], list):
            d["_recent_exact_calls"] = set(d["_recent_exact_calls"])
        return cls(d)


def create_execution_state(
    *,
    goal: str,
    sub_goals: list[Any],
    active_aspect: dict[str, Any],
    memory_influenced: list[str],
    reasoning_mode: str,
    last_reasoning_mode: str,
    persona_focus_id: str,
    conversation_id: str,
    active_plan_id: str,
    plan_approved: bool,
    steps_container: list[Any],
    execution_id: str | None = None,
) -> ExecutionState:
    """Factory used by agent_loop (and tests)."""
    return ExecutionState.create_initial(
        goal=goal,
        sub_goals=sub_goals,
        active_aspect=active_aspect,
        memory_influenced=memory_influenced,
        reasoning_mode=reasoning_mode,
        last_reasoning_mode=last_reasoning_mode,
        persona_focus_id=persona_focus_id,
        conversation_id=conversation_id,
        active_plan_id=active_plan_id,
        plan_approved=plan_approved,
        steps_container=steps_container,
        execution_id=execution_id,
    )
