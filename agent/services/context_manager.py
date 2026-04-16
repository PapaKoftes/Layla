"""
Context compression and prompt assembly.

- Conversation history: triggers at ~75% of context window; summarizes oldest messages.
- Prompt assembly: centralized layer for token budgets, deduplication, structured prompts.
  All model calls should pass through build_system_prompt() for consistency.
"""
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent

# Default token budgets per section (tunable via config)
# Aligned with context_budget.DEFAULT_BUDGETS
DEFAULT_BUDGETS = {
    "system_instructions": 800,
    "pinned_context": 400,
    "agent_state": 400,
    "current_goal": 100,
    "memory": 800,
    "knowledge_graph": 200,
    "knowledge": 800,
    "workspace_context": 400,
    "tools": 0,  # tools injected separately by orchestrator
    "conversation": 800,
    "current_task": 200,
}


def token_estimate(text: str) -> int:
    """Token count. Uses tiktoken (cl100k_base) when available, else ~4 chars/token."""
    from services.token_count import count_tokens
    return count_tokens(text)


def token_estimate_messages(messages: list) -> int:
    """Total token count for a list of {role, content} dicts."""
    from services.token_count import count_tokens_messages
    return count_tokens_messages(messages)


def effective_compact_threshold_ratio(cfg: dict | None, n_ctx: int) -> float:
    """
    Base ratio from context_auto_compact_ratio; lower (earlier) compaction when
    context_aggressive_compress_enabled and small n_ctx.
    """
    base = float((cfg or {}).get("context_auto_compact_ratio", 0.75))
    if (cfg or {}).get("context_aggressive_compress_enabled"):
        if n_ctx < 8192:
            return min(base, 0.52)
        return min(base, 0.62)
    return base


def summarize_history(
    messages: list,
    n_ctx: int = 4096,
    threshold_ratio: float = 0.75,
    keep_recent_messages: int = 0,
) -> list:
    """
    If token_count > threshold, compress oldest messages into a compact system summary.

    When keep_recent_messages > 0, the last N messages are never merged into the
    summary (sliding window): only the prefix is compressed.
    """
    threshold = int(n_ctx * threshold_ratio)
    total = token_estimate_messages(messages)
    if total <= threshold:
        return messages
    if keep_recent_messages > 0 and len(messages) > keep_recent_messages:
        suffix = messages[-keep_recent_messages:]
        prefix = messages[:-keep_recent_messages]
        if not prefix:
            return messages
        to_compress = prefix
        rest = suffix
    else:
        half = max(1, len(messages) // 2)
        to_compress = messages[:half]
        rest = messages[half:]
    summary = _compress_to_summary(to_compress)
    if summary:
        # Persist to long-term memory to prevent context overflow across sessions
        if summary.startswith("[Earlier conversation summary]"):
            try:
                from layla.memory.db import (
                    add_conversation_summary,
                    add_episode_event,
                    add_relationship_memory,
                    add_timeline_event,
                    create_episode,
                )
                add_conversation_summary(summary)
                add_relationship_memory(summary)  # companion intelligence: meaningful interaction
                tl_id = add_timeline_event(summary, event_type="conversation_summary", importance=0.5)
                ep_id = create_episode(summary=summary[:200])
                add_episode_event(ep_id, "conversation_summary", str(tl_id) if tl_id > 0 else "", "timeline_events")
            except Exception as _e:
                _logger.debug("summarize_history companion-intel write failed: %s", _e)
            try:
                from services.style_profile import update_profile_from_interactions
                update_profile_from_interactions(to_compress)
            except Exception as _e:
                _logger.debug("summarize_history style_profile update failed: %s", _e)
        compressed = [{"role": "system", "content": summary}]
        return compressed + rest
    return rest


def maybe_auto_compact(messages: list, n_ctx: int = 4096, cfg: dict | None = None) -> list:
    """Wrapper: summarize_history using effective threshold + optional keep-recent window."""
    ratio = effective_compact_threshold_ratio(cfg, n_ctx)
    keep = int((cfg or {}).get("context_sliding_keep_messages", 0) or 0)
    if (cfg or {}).get("context_aggressive_compress_enabled") and keep <= 0:
        keep = 10
    before = token_estimate_messages(messages)
    out = summarize_history(
        list(messages),
        n_ctx=n_ctx,
        threshold_ratio=ratio,
        keep_recent_messages=keep,
    )
    after = token_estimate_messages(out)
    if after < before:
        _logger.info("auto-compact: conversation tokens %s→%s", before, after)
    return out


def _compress_to_summary(messages: list) -> str:
    """Summarize oldest messages via LLM. Falls back to truncation if LLM unavailable."""
    if not messages:
        return ""
    parts = []
    for m in messages:
        role = (m.get("role") or "").lower()
        content = (m.get("content") or "").strip()
        if not content or len(content) < 10:
            continue
        content = content[:800]
        if role == "user":
            parts.append(f"User: {content}")
        else:
            parts.append(f"Assistant: {content}")
    if not parts:
        return ""
    raw = "\n".join(parts)
    try:
        import runtime_safety
        from services.llm_gateway import llm_generation_lock, llm_serialize_lock, run_completion

        cfg = runtime_safety.load_config()
        busy_lock = llm_generation_lock if cfg.get("llm_serialize_per_workspace") else llm_serialize_lock
        acquired = busy_lock.acquire(blocking=False)
        if not acquired:
            raise RuntimeError("llm busy")
        try:
            prompt = (
                "Summarize this conversation excerpt into 3-5 bullet points. "
                "Preserve: key facts, decisions made, tool results, user preferences. "
                "Be concise. Output only the bullets.\n\n" + raw
            )
            out = run_completion(prompt, max_tokens=300, temperature=0.1, stream=False)
        finally:
            busy_lock.release()
        if isinstance(out, dict):
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        else:
            text = ""
        if text and len(text.strip()) > 20:
            return "[Earlier conversation summary]\n" + text.strip()
    except Exception:
        pass
    return "[Earlier conversation (truncated)]\n" + raw[-1500:]


# ─── Prompt assembly with token budgets ──────────────────────────────────────


def truncate_to_tokens(text: str, max_tokens: int, suffix: str = "...") -> str:
    """Truncate text to fit within max_tokens. Preserves word boundaries when possible."""
    if not text or max_tokens <= 0:
        return ""
    est = token_estimate(text)
    if est <= max_tokens:
        return text
    # Binary-search-ish: reduce by ratio
    target_chars = int(len(text) * max_tokens / max(est, 1))
    truncated = text[: max(1, target_chars - len(suffix))]
    last_space = truncated.rfind(" ")
    if last_space > target_chars // 2:
        truncated = truncated[: last_space]
    return (truncated or text[:50]).strip() + suffix


def deduplicate_content(items: list[str], key_len: int = 80) -> list[str]:
    """
    Remove duplicate or near-duplicate content. Uses first key_len chars as fingerprint.
    Preserves order; first occurrence wins.
    """
    seen: set[str] = set()
    out: list[str] = []
    for item in (i for i in items if (i or "").strip()):
        fp = (item.strip()[:key_len] or "").lower()
        if fp and fp not in seen:
            seen.add(fp)
            out.append(item)
    return out


def build_system_prompt(
    sections: dict[str, str],
    n_ctx: int = 4096,
    budgets: dict[str, int] | None = None,
    reserve_for_response: int = 512,
) -> tuple[str, dict[str, Any]]:
    """
    Assemble system prompt from sections with token budget enforcement.

    Sections follow the canonical structure:
      system_instructions, agent_state, memory, knowledge_graph,
      tools, conversation, current_task

    Returns (assembled_prompt, metrics_dict).
    """
    if budgets is None:
        try:
            from services.context_budget import get_budgets
            budgets = get_budgets(n_ctx)
        except Exception:
            budgets = DEFAULT_BUDGETS.copy()
    total_budget = max(512, n_ctx - reserve_for_response)
    order = [
        "system_instructions",
        # Current goal/sub-objectives must be early so it survives token pressure.
        # This is especially important when identity/personality blocks are large.
        "current_goal",
        "agent_state",
        "pinned_context",
        "memory",
        "knowledge_graph",
        "knowledge",
        "tools",
        "conversation",
        "current_task",
    ]
    built: list[tuple[str, str]] = []  # (key, content)
    metrics: dict[str, Any] = {
        "section_tokens": {},
        "total_tokens": 0,
        "truncated_sections": [],
        "dropped_sections": [],
        "dedup_removed": 0,
    }
    remaining = total_budget
    # Reserve a small slice for critical context so large identity/personality blocks
    # can't starve the workspace context entirely (important for tests + reliability).
    _reserve_agent_state = max(60, int(budgets.get("agent_state", 120) or 120))
    _reserve_current_goal = max(40, int(budgets.get("current_goal", 60) or 60))

    for key in order:
        raw = (sections.get(key) or "").strip()
        if not raw:
            continue
        max_tok = budgets.get(key, 400)
        if key == "system_instructions":
            # Leave room for goal + workspace context if they exist.
            _need_goal = 1 if (sections.get("current_goal") or "").strip() else 0
            _need_state = 1 if (sections.get("agent_state") or "").strip() else 0
            reserve = (_reserve_current_goal if _need_goal else 0) + (_reserve_agent_state if _need_state else 0)
            if remaining > reserve:
                max_tok = min(int(max_tok), int(remaining - reserve))
        elif key == "current_goal":
            # Leave room for workspace context.
            if (sections.get("agent_state") or "").strip() and remaining > _reserve_agent_state:
                max_tok = min(int(max_tok), int(remaining - _reserve_agent_state))
        max_tok = min(max_tok, remaining)
        if max_tok <= 0:
            metrics["dropped_sections"].append(key)
            _logger.debug("context_budget: dropped section=%s (budget exhausted, remaining=%d)", key, remaining)
            break
        truncated = truncate_to_tokens(raw, max_tok)
        tok = token_estimate(truncated)
        if tok > max_tok:
            truncated = truncate_to_tokens(raw, max_tok - 20)
            tok = token_estimate(truncated)
        metrics["section_tokens"][key] = tok
        if tok < token_estimate(raw):
            metrics["truncated_sections"].append(key)
        remaining = max(0, remaining - tok - 2)  # newline overhead
        if truncated:
            built.append((key, truncated))

    # Deduplicate memory-like sections (learnings, semantic, graph can overlap)
    memory_keys = {"memory", "knowledge_graph"}
    mem_contents = [c for k, c in built if k in memory_keys]
    if len(mem_contents) > 1:
        deduped = deduplicate_content(mem_contents)
        metrics["dedup_removed"] = len(mem_contents) - len(deduped)
        # Rebuild: non-memory first, then single merged memory block
        non_mem = [(k, c) for k, c in built if k not in memory_keys]
        merged_mem = "\n".join(deduped) if deduped else ""
        built = non_mem + ([("memory", merged_mem)] if merged_mem else [])

    parts = [c for _, c in built]
    final = "\n\n".join(parts) if parts else ""
    metrics["total_tokens"] = token_estimate(final)

    try:
        from services.observability import log_prompt_assembled
        log_prompt_assembled(
            total_tokens=metrics["total_tokens"],
            sections=len([k for k in order if (sections.get(k) or "").strip()]),
            truncated=len(metrics["truncated_sections"]),
        )
    except Exception:
        pass

    return final, metrics


def truncate_tool_output_for_prompt(text: str, max_tokens: int = 500) -> str:
    """Cap tool/step blobs so decision prompts stay small on low n_ctx."""
    if not text:
        return ""
    t = str(text).strip()
    if not t:
        return ""
    return truncate_to_tokens(t, max(64, max_tokens), suffix="\n...[truncated for context]\n")
