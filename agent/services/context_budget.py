"""
Token budgeting for prompt sections.
Allocates limits per section to prevent context overflow.
Integrates with context_manager.build_system_prompt().
Uses services/token_count.py (tiktoken) for accurate counting.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")

# Default token budgets per section (tunable via config prompt_budgets)
DEFAULT_BUDGETS: dict[str, int] = {
    "identity": 400,
    "memory": 800,
    "knowledge": 800,
    "graph_context": 200,
    "workspace_context": 400,
    # Legacy keys used by context_manager
    "system_instructions": 800,
    "agent_state": 400,
    "current_goal": 100,
    "knowledge_graph": 200,
    "tools": 0,
    "conversation": 800,
    "current_task": 200,
}


def get_budgets(cfg: dict | None = None) -> dict[str, int]:
    """
    Return token budgets for each prompt section.
    Merges config prompt_budgets over defaults.
    """
    budgets = dict(DEFAULT_BUDGETS)
    if cfg is None:
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    overrides = cfg.get("prompt_budgets") or {}
    for k, v in overrides.items():
        if k in budgets and v is not None:
            budgets[k] = max(0, int(v))
    return budgets


def truncate_section(text: str, max_tokens: int, section_name: str = "") -> str:
    """
    Truncate text to fit within max_tokens.
    Preserves word boundaries when possible.
    Uses token_count for accuracy.
    """
    if not text or max_tokens <= 0:
        return ""
    try:
        from services.token_count import count_tokens
        est = count_tokens(text)
    except Exception:
        est = max(1, len(text) // 4)
    if est <= max_tokens:
        return text
    suffix = "..."
    target_chars = int(len(text) * max_tokens / max(est, 1))
    truncated = text[: max(1, target_chars - len(suffix))]
    last_space = truncated.rfind(" ")
    if last_space > target_chars // 2:
        truncated = truncated[: last_space]
    return (truncated or text[:50]).strip() + suffix
