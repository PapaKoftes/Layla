"""
Structured decision schema for the agent planning layer.
Uses Pydantic when available for validation; normalizes action/tool/priority.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from pydantic import BaseModel, Field
    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False
    BaseModel = None  # type: ignore
    Field = None  # type: ignore


if _HAS_PYDANTIC and BaseModel is not None:

    class AgentDecision(BaseModel):
        """Schema for one LLM decision (tool, reason, or think).

        batch_tools: optional list of additional concurrency_safe tool names to
        run in parallel alongside the primary tool in this same step.
        Each item is {"tool": name, "args": {…}}.
        """
        model_config = {"extra": "ignore"}
        action: str = "reason"
        tool: str | None = None
        args: dict[str, Any] = Field(default_factory=dict)
        batch_tools: list[dict[str, Any]] = Field(default_factory=list)
        thought: str | None = None
        objective_complete: bool = False
        revised_objective: str | None = None
        priority_level: str = "medium"
        impact_estimate: str | None = None
        effort_estimate: str | None = None
        risk_estimate: str | None = None


def _first_json_line(text: str) -> str | None:
    """Return the first line that looks like a JSON object."""
    if not (text or "").strip():
        return None
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if line.startswith("{"):
            return line
    return None


def _str_opt(val: Any, max_len: int = 80) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        return val.strip() or None
    return str(val)[:max_len] if val else None


def parse_decision(text: str, valid_tools: frozenset[str]) -> dict | None:
    """
    Parse LLM output into a decision dict. Optionally validates with Pydantic.
    Normalizes action, tool, priority_level; returns None if no valid JSON.
    """
    raw = _first_json_line(text)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    if _HAS_PYDANTIC and BaseModel is not None:
        try:
            AgentDecision.model_validate(data)
        except Exception:
            return None

    action = (data.get("action") or "reason").lower().strip()
    if action not in ("tool", "reason", "none", "think"):
        action = "reason"
    tool = (data.get("tool") or "").strip() or None
    if action in ("none", "think"):
        tool = None
    elif action == "tool" and tool and tool not in valid_tools:
        tool = None
    revised = _str_opt(data.get("revised_objective"), 500)
    pl = (data.get("priority_level") or "").strip().lower()
    if pl not in ("low", "medium", "high"):
        pl = "medium"
    args = data.get("args")
    if not isinstance(args, dict):
        args = {}

    # batch_tools — list of {"tool": name, "args": {...}} for parallel execution
    batch_raw = data.get("batch_tools")
    batch_tools: list[dict] = []
    if isinstance(batch_raw, list):
        for bt in batch_raw:
            if isinstance(bt, dict):
                bt_name = (bt.get("tool") or "").strip()
                bt_args = bt.get("args") if isinstance(bt.get("args"), dict) else {}
                if bt_name and bt_name in valid_tools:
                    batch_tools.append({"tool": bt_name, "args": bt_args})

    return {
        "action": action,
        "tool": tool,
        "args": args,
        "batch_tools": batch_tools,
        "thought": _str_opt(data.get("thought"), 4000),
        "objective_complete": bool(data.get("objective_complete", False)),
        "revised_objective": revised,
        "priority_level": pl,
        "impact_estimate": _str_opt(data.get("impact_estimate")),
        "effort_estimate": _str_opt(data.get("effort_estimate")),
        "risk_estimate": _str_opt(data.get("risk_estimate")),
    }
