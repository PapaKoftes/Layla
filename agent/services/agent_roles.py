"""
Optional multi-agent-style coordination hints (single LLM, prompt-only).
Enabled only when multi_agent_orchestration_enabled and reasoning_mode is deep.
"""
from __future__ import annotations

ORGANIZATION_RULES = (
    "Organization: prefer minimal diffs, avoid new files unless necessary, do not bloat the repo, "
    "keep outputs reviewable, and reject sloppy or redundant changes."
)

CRITIC_REMINDER = (
    "Self-check: verify assumptions against tools and files; if uncertain, say so and propose a concrete check."
)


def deep_task_coordination_prompt() -> str:
    """Short block appended to system head for deep tasks."""
    return (
        "Multi-agent discipline (single pass): plan briefly, implement precisely, then sanity-check.\n"
        + ORGANIZATION_RULES
        + "\n"
        + CRITIC_REMINDER
    )
