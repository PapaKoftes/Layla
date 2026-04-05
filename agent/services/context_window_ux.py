"""Context-window SSE hints (extracted from agent_loop)."""

from __future__ import annotations

import logging
import queue
from typing import Callable

logger = logging.getLogger("layla")


def emit_context_window_ux(
    ux_state_queue: queue.Queue | None,
    conversation_history: list | None,
    cfg: dict,
    state: dict,
    *,
    format_steps: Callable[[list], str],
) -> None:
    """SSE hint when estimated prompt+history usage exceeds 70%/90% of n_ctx."""
    if ux_state_queue is None:
        return
    try:
        from services.context_manager import token_estimate, token_estimate_messages

        n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
        msgs = conversation_history or []
        base = token_estimate_messages(msgs)
        extra = token_estimate((state.get("original_goal") or "")[:12000])
        extra += token_estimate(format_steps(state.get("steps") or [])[:8000])
        used = min(base + extra, int(n_ctx * 1.15))
        pct = used / float(n_ctx) if n_ctx else 0.0
        pct_i = round(pct * 100, 1)
        if pct >= 0.9:
            ux_state_queue.put(
                {"_type": "ctx_warn", "ux_state": "context_critical", "ctx_pct": pct_i},
                block=False,
            )
        elif pct >= 0.7:
            ux_state_queue.put(
                {"_type": "ctx_warn", "ux_state": "approaching_context_limit", "ctx_pct": pct_i},
                block=False,
            )
    except Exception as e:
        logger.debug("context ux emit: %s", e)
