"""
Canonical ordering for memory-block sections in the system prompt.
See docs/MEMORY_PRECEDENCE.md.
"""
from __future__ import annotations

# Keys must match those used in agent_loop._build_system_head when building memory_sections dict.
MEMORY_SECTION_ORDER: tuple[str, ...] = (
    "git_preamble",
    "project_instructions",
    "repo_cognition",
    "project_memory",
    "relationship_codex",
    "skills",
    "aspect_memories",
    "learnings",
    "semantic_recall",
    "retrieved_context",
    "conversation_summaries",
    "relationship_memory",
    "timeline_events",
    "style_and_identity",
    "personal_knowledge_graph",
    "rl_feedback",
    "reasoning_strategies",
)


def merge_memory_sections(sections: dict[str, str]) -> str:
    """Join non-empty sections in precedence order."""
    parts: list[str] = []
    for key in MEMORY_SECTION_ORDER:
        raw = (sections.get(key) or "").strip()
        if raw:
            parts.append(raw)
    return "\n\n".join(parts)
