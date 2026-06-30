"""Step formatting utilities for the agent loop.

Extracted from agent_loop.py: windowed step formatting and deterministic
step summarization.
"""

from __future__ import annotations

import logging

import runtime_safety
from layla.tools.registry import TOOLS
from services.infrastructure.agent_loop_formatting import format_tool_steps_for_prompt as _format_steps_impl

logger = logging.getLogger("layla")

__all__ = ["VALID_TOOLS", "format_steps", "summarize_steps_deterministic"]

# Valid tool names for LLM decision (must match TOOLS registry)
VALID_TOOLS: frozenset[str] = frozenset(TOOLS.keys())


def format_steps(steps: list) -> str:
    """Window tool-step formatting to avoid unbounded prompt growth."""
    try:
        cfg = runtime_safety.load_config()
        n = int(cfg.get("tool_steps_window", 25) or 25)
    except Exception as e:
        logger.debug("tool_steps_window config load failed: %s", e, exc_info=True)
        n = 25
    try:
        if n > 0 and isinstance(steps, list) and len(steps) > n:
            steps = steps[-n:]
    except Exception as e:
        logger.debug("steps window trim failed: %s", e, exc_info=True)
        pass
    return _format_steps_impl(steps)


def summarize_steps_deterministic(steps: list, *, keep_last: int = 5, max_lines: int = 10) -> str:
    """
    Deterministic step summarization (no LLM).
    Summarizes older steps so weak models don't drown in long tool traces.
    """
    if not isinstance(steps, list) or len(steps) <= keep_last:
        return ""
    prefix = steps[: max(0, len(steps) - keep_last)]
    lines: list[str] = []
    n = 0
    for s in prefix:
        if not isinstance(s, dict):
            continue
        act = str(s.get("action") or "")
        if not act:
            continue
        r = s.get("result")
        ok = None
        extra = ""
        if isinstance(r, dict):
            ok = r.get("ok")
            p = r.get("path")
            if isinstance(p, str) and p.strip():
                extra = f" path={p.strip()}"
            rc = r.get("returncode")
            if rc is not None and act in ("shell", "run_python"):
                extra = (extra + f" rc={rc}").strip()
        elif isinstance(r, str) and act == "reason":
            ok = True
        status = "ok" if ok else "fail" if ok is False else "?"
        lines.append(f"- {act} ÃÃ¥Ã {status}{extra}")
        n += 1
        if n >= max_lines:
            break
    if not lines:
        return ""
    return "Steps completed so far (compressed):\n" + "\n".join(lines)
