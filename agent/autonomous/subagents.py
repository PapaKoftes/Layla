from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SubagentRequest:
    """Phase 2: bounded helpers (max 3, depth 1)."""

    goal: str
    hint: str = ""


def run_subagents(
    *,
    requests: list[SubagentRequest],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Phase 2 (minimal stub):
    - Enforces bounds and returns empty results without starting nested autonomy.
    - Intentionally does NOT call agent_loop or spawn background workers.
    """
    max_n = int(cfg.get("autonomous_max_subagents") or 3)
    max_n = max(0, min(3, max_n))
    reqs = list(requests or [])[:max_n]
    out: list[dict[str, Any]] = []
    for r in reqs:
        out.append({"ok": False, "error": "subagents_not_enabled", "goal": r.goal, "hint": r.hint})
    return out

