"""
agent/core/loop.py — Planned hook for extracting the autonomous execution pipeline.

**Ground truth today:** `agent_loop.autonomous_run()` does **not** import or call
`run_loop()`. The live path builds `state["_snapshot"]` by calling
`core.observer.build_snapshot` directly inside `agent_loop` (see grep for
`build_snapshot` in `agent_loop.py`).

This module holds a **Tier 3 extraction stub**: `run_loop()` only performs the
observe/snapshot step and returns `state` so a future refactor could thread the
same API. Plan → approve → execute → validate → update_state remain **only** in
`agent_loop` until extraction proceeds.

Status: extraction in progress; do not assume the 6-phase pipeline is
implemented here — read `agent_loop.py` for actual control flow.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def run_loop(
    goal: str,
    cfg: dict,
    state: dict,
    *,
    allow_write: bool = False,
    allow_run: bool = False,
    workspace: str = "",
    aspect_id: str = "",
    conversation_history: list | None = None,
    stream_final: bool = False,
    ux_state_queue: Any = None,
    model_override: str | None = None,
    reasoning_effort: str | None = None,
    persona_focus: str = "",
) -> dict[str, Any]:
    """
    Tier-3 stub: attach an observation snapshot to `state` and return.

    **Not** the live autonomous loop entrypoint — `autonomous_run` does not call
    this function today. Full tool/decision cycling lives in `agent_loop.py`.

    When extraction completes, this function (or successors) should own phased
    boundaries; until then, treat it as experimental API surface only.
    """
    from core.observer import build_snapshot

    snapshot = build_snapshot(
        goal=goal,
        conversation_id=state.get("conversation_id", ""),
        cfg=cfg,
        aspect_id=aspect_id,
        conversation_history=conversation_history,
        workspace_root=workspace,
        allow_write=allow_write,
        allow_run=allow_run,
    )
    state["_snapshot"] = snapshot

    # Decision loop, tools, approvals, and completion remain in agent_loop.
    return state
