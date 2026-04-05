"""Shared formatting helpers for the agent loop (extracted from agent_loop for testability)."""


def format_tool_steps_for_prompt(steps: list) -> str:
    """Format tool steps for feeding back into the next iteration or reason prompt."""
    if not steps:
        return ""
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
            lines.append(f"{action}: {str(summary)[:600]}")
        else:
            lines.append(f"{action}: {str(result)[:600]}")
    return "\n".join(lines)
