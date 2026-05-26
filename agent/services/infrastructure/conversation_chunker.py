# -*- coding: utf-8 -*-
"""
conversation_chunker.py — Auto-split long autonomous tasks into chunks.

For autonomous tasks exceeding a step threshold (default 50), this module
generates handoff summaries so each chunk starts with compressed prior state
rather than raw conversation history. Memory carries forward via learnings.

Config keys:
    auto_chunk_long_tasks       bool  (default true)
    chunk_step_threshold        int   (default 50)
    chunk_handoff_max_tokens    int   (default 600)

Usage:
    from services.conversation_chunker import should_chunk, build_handoff_summary
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("layla")


@dataclass
class ChunkHandoff:
    """Compressed state for handing off between conversation chunks."""
    chunk_number: int
    total_steps_so_far: int
    goal: str
    completed_actions: list[str] = field(default_factory=list)
    pending_actions: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    context_summary: str = ""
    created_at: float = field(default_factory=time.time)


def _cfg() -> dict:
    try:
        from services.config_cache import get_config
        return get_config()
    except Exception:
        try:
            import runtime_safety
            return runtime_safety.load_config()
        except Exception:
            return {}


def should_chunk(step_count: int, cfg: dict | None = None) -> bool:
    """Return True if the autonomous run should create a chunk boundary."""
    cfg = cfg or _cfg()
    if not cfg.get("auto_chunk_long_tasks", True):
        return False
    threshold = max(10, int(cfg.get("chunk_step_threshold", 50)))
    return step_count > 0 and step_count % threshold == 0


def build_handoff_summary(
    goal: str,
    messages: list[dict],
    step_count: int,
    *,
    chunk_number: int = 1,
    state: dict | None = None,
    cfg: dict | None = None,
) -> ChunkHandoff:
    """
    Build a compressed handoff for the next conversation chunk.

    Extracts completed actions and key findings from message history,
    then compresses into a structured summary.
    """
    cfg = cfg or _cfg()
    max_tokens = int(cfg.get("chunk_handoff_max_tokens", 600))
    state = state or {}

    completed: list[str] = []
    findings: list[str] = []
    pending: list[str] = []

    # Extract action history from messages
    for msg in messages:
        role = (msg.get("role") or "").lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue

        if role == "assistant":
            # Look for tool calls / actions
            if any(kw in content.lower() for kw in ("executed", "completed", "wrote", "created", "fixed", "updated")):
                completed.append(content[:120])
            elif any(kw in content.lower() for kw in ("found", "discovered", "result", "shows", "indicates")):
                findings.append(content[:120])

    # Extract pending from state if available
    if state.get("plan") and isinstance(state["plan"], dict):
        steps = state["plan"].get("steps", [])
        for s in steps:
            if isinstance(s, dict) and s.get("status") in ("pending", "in_progress"):
                pending.append(str(s.get("name", s.get("action", "")))[:80])

    # Build compressed context summary
    context_parts = []
    if completed:
        context_parts.append("Completed: " + "; ".join(completed[-5:]))
    if findings:
        context_parts.append("Found: " + "; ".join(findings[-5:]))
    if pending:
        context_parts.append("Pending: " + "; ".join(pending[:5]))

    context_summary = "\n".join(context_parts)

    # Compress if too long
    try:
        from services.token_count import count_tokens
        if count_tokens(context_summary) > max_tokens:
            from services.prompt_compressor import compress
            result = compress(context_summary, token_budget=max_tokens)
            context_summary = result.get("compressed", context_summary)
    except Exception:
        # Hard truncate as fallback
        context_summary = context_summary[:max_tokens * 4]

    return ChunkHandoff(
        chunk_number=chunk_number,
        total_steps_so_far=step_count,
        goal=goal,
        completed_actions=completed[-10:],
        pending_actions=pending[:10],
        key_findings=findings[-10:],
        context_summary=context_summary,
    )


def format_continuation_prompt(handoff: ChunkHandoff) -> str:
    """
    Format a ChunkHandoff into a system prompt for the next chunk.

    This becomes the "task continuation prompt" injected at the start
    of the new chunk's context.
    """
    parts = [
        f"[Task Continuation — Chunk {handoff.chunk_number + 1}]",
        f"Original goal: {handoff.goal}",
        f"Steps completed so far: {handoff.total_steps_so_far}",
    ]

    if handoff.context_summary:
        parts.append(f"\nPrior context:\n{handoff.context_summary}")

    if handoff.pending_actions:
        parts.append("\nRemaining actions:")
        for a in handoff.pending_actions[:5]:
            parts.append(f"  - {a}")

    parts.append("\nContinue from where the previous chunk left off.")
    return "\n".join(parts)


def save_chunk_to_memory(handoff: ChunkHandoff) -> None:
    """Persist chunk handoff as a learning so it survives context boundaries."""
    try:
        from services.memory_router import save_learning
        content = (
            f"[Chunk {handoff.chunk_number} handoff] Goal: {handoff.goal}\n"
            f"Steps: {handoff.total_steps_so_far}\n"
            f"{handoff.context_summary}"
        )
        save_learning(
            content=content[:3000],
            kind="session_chunk",
            tags=f"chunk_{handoff.chunk_number}, autonomous",
        )
    except Exception as exc:
        logger.debug("save_chunk_to_memory failed: %s", exc)
