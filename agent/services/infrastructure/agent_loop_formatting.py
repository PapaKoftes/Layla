"""Shared formatting helpers for the agent loop (extracted from agent_loop for testability)."""

from __future__ import annotations

from typing import Any


def format_tool_steps_for_prompt(steps: list, cfg: dict[str, Any] | None = None) -> str:
    """Format tool steps for feeding back into the next iteration or reason prompt."""
    if not steps:
        return ""
    if cfg is None:
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    from services.context_manager import truncate_tool_output_for_prompt

    max_tok = int(cfg.get("tool_step_context_max_tokens", 500) or 500)
    if cfg.get("context_aggressive_compress_enabled"):
        max_tok = min(max_tok, 320)

    lines = []
    for s in steps:
        action = s.get("action", "")
        result = s.get("result", {})
        if isinstance(result, dict):
            summary = result.get("content") or result.get("output") or result.get("matches")
            if summary is None and result.get("entries"):
                summary = str(result["entries"])[:300]
            if summary is None:
                summary = "ok" if result.get("ok") else result.get("error", str(result)[:200])
            if isinstance(summary, (list, dict)):
                summary = str(summary)[:400]
            blob = str(summary)
        else:
            blob = str(result)
        blob = truncate_tool_output_for_prompt(blob, max_tokens=max_tok)
        lines.append(f"{action}: {blob}")
    return "\n".join(lines)
