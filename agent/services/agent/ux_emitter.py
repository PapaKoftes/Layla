"""
UX event emission for the agent loop.

Extracted from agent_loop.py — Phase 2 decomposition.
Handles streaming UX state, tool progress, and context window events.
"""
from __future__ import annotations

import json
import logging
import queue
import time
from collections.abc import Callable

logger = logging.getLogger("layla")


class BackgroundProgressSteps(list):
    """Notify background_progress_callback on append (throttled) for task observability."""

    __slots__ = ("_cb", "_interval", "_last_emit", "_seq")

    def __init__(self, cb: Callable[[dict], None], interval: float = 0.35) -> None:
        super().__init__()
        self._cb = cb
        self._interval = max(0.05, float(interval))
        self._last_emit = 0.0
        self._seq = 0

    def append(self, item: object) -> None:
        super().append(item)
        try:
            now = time.monotonic()
            force = False
            if isinstance(item, dict):
                act = item.get("action")
                if act in ("client_abort", "reason", "none", "think"):
                    force = True
            if not force and now - self._last_emit < self._interval:
                return
            self._last_emit = now
            self._seq += 1
            preview = ""
            if isinstance(item, dict):
                try:
                    preview = json.dumps(item.get("result"), default=str)[:400]
                except Exception as e:
                    logger.debug("progress step preview serialization failed: %s", e, exc_info=True)
                    preview = str(item.get("result"))[:400]
            self._cb(
                {
                    "seq": self._seq,
                    "t": time.time(),
                    "action": item.get("action") if isinstance(item, dict) else None,
                    "preview": preview,
                    "step_index": len(self) - 1,
                }
            )
        except Exception as _exc:
            logger.debug("BackgroundProgressSteps.append: %s", _exc, exc_info=False)


def emit_ux(state: dict, ux_state_queue: queue.Queue | None, label: str) -> None:
    """Append UX state for this turn and optionally push to queue for live SSE."""
    state.setdefault("ux_states", []).append(label)
    if ux_state_queue is not None:
        try:
            ux_state_queue.put(label, block=False)
        except Exception as e:
            logger.debug("emit_ux put failed: %s", e)


def emit_tool_start(ux_state_queue: queue.Queue | None, tool_name: str) -> None:
    """Emit a tool_start event so the UI can show 'Running tool_name...' during streaming."""
    logger.info("tool start: %s", tool_name)
    if ux_state_queue is not None:
        try:
            ux_state_queue.put({"_type": "tool_start", "tool": tool_name}, block=False)
        except Exception as e:
            logger.debug("emit_tool_start put failed: %s", e)


def summarize_tool_result(result: object, max_len: int = 220) -> tuple[bool | None, str]:
    """Small, UI-safe summary for streaming tool trace."""
    ok: bool | None = None
    try:
        if isinstance(result, dict):
            if "ok" in result:
                ok = bool(result.get("ok"))
            msg = (
                result.get("message")
                or result.get("error")
                or result.get("reason")
                or result.get("status")
                or ""
            )
            s = msg if isinstance(msg, str) else str(msg)
        elif isinstance(result, str):
            s = result
        else:
            s = str(result)
    except Exception as e:
        logger.debug("summarize_tool_result failed: %s", e, exc_info=True)
        s = ""
    s = (s or "").strip().replace("\n", " ")
    if len(s) > max_len:
        s = s[:max_len - 3].rstrip() + "..."
    return ok, s


def emit_tool_step(ux_state_queue: queue.Queue | None, tool_name: str, result: object) -> None:
    """Emit a tool_step event so the UI can show step-by-step progress during streaming."""
    if ux_state_queue is None:
        return
    ok, summary = summarize_tool_result(result)
    try:
        ux_state_queue.put(
            {"_type": "tool_step", "phase": "end", "tool": tool_name, "ok": ok, "summary": summary},
            block=False,
        )
    except Exception as e:
        logger.debug("emit_tool_step put failed: %s", e)


def emit_context_window_ux(
    ux_state_queue: queue.Queue | None,
    conversation_history: list | None,
    cfg: dict,
    state: dict,
    *,
    format_steps_fn=None,
) -> None:
    """Delegate to services.context_window_ux (keeps call sites stable)."""
    from services.context_window_ux import emit_context_window_ux as _emit
    _emit(
        ux_state_queue,
        conversation_history,
        cfg,
        state,
        format_steps=format_steps_fn,
    )
