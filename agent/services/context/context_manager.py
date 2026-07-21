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

AGENT_DIR = Path(__file__).resolve().parent.parent.parent

# Module-level store for last build_system_prompt() metrics (thread-safe via GIL for dict assignment)
_last_prompt_metrics: dict = {}
_last_prompt_n_ctx: int = 4096


def record_prompt_metrics(metrics: dict, n_ctx: int = 4096) -> None:
    """Store metrics from the most recent build_system_prompt() call for telemetry queries."""
    global _last_prompt_metrics, _last_prompt_n_ctx
    _last_prompt_metrics = dict(metrics)
    _last_prompt_n_ctx = n_ctx


def get_last_prompt_metrics() -> tuple[dict, int]:
    """Retrieve the most recently recorded prompt assembly metrics and n_ctx."""
    return _last_prompt_metrics.copy(), _last_prompt_n_ctx

# Default token budgets per section (tunable via config)
# Aligned with context_budget.DEFAULT_BUDGETS
DEFAULT_BUDGETS = {
    "system_instructions": 800,
    "durable_facts": 250,
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
    from services.llm.token_count import count_tokens
    return count_tokens(text)


def token_estimate_messages(messages: list) -> int:
    """Total token count for a list of {role, content} dicts."""
    from services.llm.token_count import count_tokens_messages
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
    force: bool = False,
) -> list:
    """
    If token_count > threshold, compress oldest messages into a compact system summary.

    When keep_recent_messages > 0, the last N messages are never merged into the
    summary (sliding window): only the prefix is compressed.

    `force` compacts regardless of token count. It exists because the caller on the live turn path
    watches a FIXED-LENGTH ring buffer (shared_state._conv_histories, deque(maxlen=20)), and token
    pressure is the wrong proxy for one: a ring never builds pressure, it discards from the left.
    Measured, the deque plateaus around 1428 tokens against a 4915-token threshold — 29% — so this
    branch had never once been taken and conversation_summaries had 0 rows for the life of the DB.
    Occupancy is the signal that matters there; see shared_state._compact_bg.
    """
    threshold = int(n_ctx * threshold_ratio)
    total = token_estimate_messages(messages)
    if not force and total <= threshold:
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
    _persisted_kind = bool(summary) and summary.startswith("[Earlier conversation summary]")
    if force and not _persisted_kind:
        # PROACTIVE compaction must never destroy what it cannot save. _compress_to_summary takes
        # the LLM lock with blocking=False and degrades to "[Earlier conversation (truncated)]" under
        # contention — a marker that is deliberately NOT written to long-term memory. Replacing real
        # messages with it would delete the very turns this call exists to preserve. Bail and retry on
        # the next assistant turn; the ring still holds everything, and compaction is idempotent.
        #
        # The non-forced path deliberately still truncates: there the context is genuinely
        # overflowing, so shedding tokens beats failing to fit at all. Only the proactive caller,
        # which has slack by construction, can afford to wait.
        _logger.debug("forced compaction skipped: summarizer unavailable, retrying next turn")
        return messages
    if summary:
        # Persist to long-term memory to prevent context overflow across sessions
        if _persisted_kind:
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
                from services.personality.style_profile import update_profile_from_interactions
                update_profile_from_interactions(to_compress)
            except Exception as _e:
                _logger.debug("summarize_history style_profile update failed: %s", _e)
        compressed = [{"role": "system", "content": summary}]
        return compressed + rest
    return rest


def maybe_auto_compact(messages: list, n_ctx: int = 4096, cfg: dict | None = None, force: bool = False) -> list:
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
        force=force,
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
        from services.llm.llm_gateway import llm_generation_lock, llm_serialize_lock, run_completion

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
    """Truncate text to fit within max_tokens. Prefers LINE boundaries, then word boundaries.

    Line boundary first, because the blocks this cuts are line-structured (markdown bullets, the
    capability manifest, memory lists) and a word-boundary cut lands mid-clause. Measured on the
    capability manifest, a word-boundary cut ended the prompt with "...no search tool in it means I" —
    a dangling half-sentence that inverts the disclosure it was in the middle of making. A half-line is
    worse than no line: the model completes it, and what it completes is not what the line said.

    Falls back to the word boundary when the nearest newline is further back than 25% of the budget, so
    a block with very long lines does not lose a quarter of its content to boundary alignment.
    """
    if not text or max_tokens <= 0:
        return ""
    est = token_estimate(text)
    if est <= max_tokens:
        return text
    # Binary-search-ish: reduce by ratio
    target_chars = int(len(text) * max_tokens / max(est, 1))
    truncated = text[: max(1, target_chars - len(suffix))]
    last_newline = truncated.rfind("\n")
    if last_newline > int(len(truncated) * 0.75):
        truncated = truncated[:last_newline]
    else:
        last_space = truncated.rfind(" ")
        if last_space > target_chars // 2:
            truncated = truncated[: last_space]
    truncated = _drop_dangling_headers(truncated) or truncated
    return (truncated or text[:50]).strip() + suffix


def _drop_dangling_headers(text: str) -> str:
    """Drop trailing markdown headers that the cut left with no body.

    Preferring the LINE boundary above means the cut lands cleanly between lines — which is right for
    prose, and produces a specific defect on markdown: when the boundary falls just after a heading, the
    section ends on a bare `## Chat style` and the suffix turns it into `## Chat style...`.

    Measured on an ordinary turn with the real Morrigan persona: every head ended with a literal
    `## Chat style...` and nothing under it. A heading with no content is not merely wasted tokens — it
    is a malformed instruction the model reads and imitates, and "here is a section about how to talk,
    now say nothing about it" is a strange thing to hand a 3B.

    Empty lines before the header go too, otherwise the section ends on trailing whitespace. Returns ""
    if everything was a header, and the caller keeps the un-dropped text in that case rather than
    emitting an empty section.

    KNOWN LIMITATION — `startswith("#")` is also true of the comment marker in Python, shell, YAML,
    TOML and Dockerfile, so a truncated code snippet can have trailing comments eaten as if they were
    headings (measured: 3 `# NOTE:` lines off a Python snippet, 8 of 10 lines off a mostly-comment
    shell excerpt, because each comment the loop eats exposes the one above it).

    Narrowing to `^#{2,6}\s` to spare them was tried and REVERTED: the head genuinely contains
    LEVEL-1 headings from knowledge and workspace sections, and under the CI stub config an ordinary
    turn then ended on a bare `# API design patterns...` — the exact production defect this function
    exists to prevent, caught by `test_ordinary_turn_head_has_no_empty_persona_section`. Level is not
    the signal that separates a heading from a comment, and no cheap proxy for it was found.

    Left as-is deliberately: eating a few trailing comment lines from an already-truncated snippet is
    the smaller harm, and it is bounded (only the tail). Fixing it properly needs fence-awareness
    (content inside ``` is code, not markdown), which is a real change to the truncation contract
    rather than a one-line predicate swap.
    """
    lines = text.split("\n")
    while lines:
        last = lines[-1].strip()
        if not last or last.startswith("#"):
            lines.pop()
            continue
        break
    return "\n".join(lines)


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


def default_budgets_for(n_ctx: int) -> dict[str, int]:
    """The per-section budgets build_system_prompt falls back to when the caller passes none.

    Extracted so a caller that needs to RAISE one section (system_head_builder widens
    `system_instructions` to fit the capability manifest) can start from the same dict this function
    would have chosen, instead of assuming DEFAULT_BUDGETS and quietly inflating every other section
    on a small model.

    Small-model guard: when the context window is ≤ 4096 tokens, the full 18-section injection
    overflows the window by ~2000+ tokens before the model can respond. Cap aggressively so
    identity + task + 1-2 memories fit with room to reply.
    """
    if n_ctx <= 4096:
        return {
            "system_instructions": 600,   # identity + aspect only, no tool list
            "current_goal": 80,
            "agent_state": 0,             # skip scratchpad entirely
            "pinned_context": 0,          # skip
            "memory": 300,                # 1-2 relevant memories max
            "knowledge_graph": 0,
            "knowledge": 0,
            "tools": 0,
            "conversation": 400,          # last 3-4 turns
            "current_task": 60,
        }
    try:
        from services.context.context_budget import get_budgets
        return dict(get_budgets(n_ctx))
    except Exception:
        return DEFAULT_BUDGETS.copy()


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
        budgets = default_budgets_for(n_ctx)
    total_budget = max(512, n_ctx - reserve_for_response)

    # Phase 5: Dynamic budget reallocation based on last-known section pressure
    try:
        from services.context.context_budget import rebalance_budget
        _prev_metrics, _ = get_last_prompt_metrics()
        if _prev_metrics and _prev_metrics.get("section_tokens"):
            budgets = rebalance_budget(
                budgets,
                section_tokens=_prev_metrics["section_tokens"],
            )
    except Exception:
        pass

    order = [
        "system_instructions",
        # Durable identity facts are authoritative ground truth — placed right after
        # the identity block (and ahead of goal/memory/knowledge) so token pressure
        # can never crowd the user's name/timezone/tooling out of context.
        "durable_facts",
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
    use_structure_labels = True
    try:
        import runtime_safety

        use_structure_labels = bool((runtime_safety.load_config() or {}).get("prompt_structure_labels", True))
    except Exception:
        pass
    _hdr_task_done = False
    _hdr_ctx_done = False
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
    # Reserve what the section actually NEEDS (its content size), capped by its budget —
    # reserving the full nominal budget starved SYSTEM on small windows: a 25-token
    # agent_state reserved 400 tokens, leaving identity+persona ~12 tokens, and the
    # whole SYSTEM section silently vanished on low tiers.
    # +24 pad covers the "## TASK"/"## SCRATCHPAD" structure headers and estimator noise so the
    # reserved section actually fits whole instead of losing its tail by a couple of tokens.
    _reserve_agent_state = min(
        max(60, int(budgets.get("agent_state", 120) or 120)),
        token_estimate((sections.get("agent_state") or "").strip()) + 24,
    )
    _reserve_current_goal = min(
        max(40, int(budgets.get("current_goal", 60) or 60)),
        token_estimate((sections.get("current_goal") or "").strip()) + 24,
    )
    # Durable identity facts (name/timezone/tooling) are authoritative ground truth and the
    # `order` list places them right after SYSTEM precisely so they survive token pressure — but
    # that only holds if SYSTEM's greedy allocation actually LEAVES room for them. Reserve the
    # durable-facts content (capped) the same way agent_state/current_goal are reserved, or a large
    # identity+personality block starves them on small windows and the section is truncated down to a
    # bare header + "…" (the user's name silently vanishes from the prompt on low tiers).
    _reserve_durable_facts = min(
        max(40, int(budgets.get("durable_facts", 200) or 200)),
        token_estimate((sections.get("durable_facts") or "").strip()) + 24,
    )

    for key in order:
        raw = (sections.get(key) or "").strip()
        if not raw:
            continue
        if use_structure_labels:
            if key == "system_instructions":
                raw = "## SYSTEM\n\n" + raw
            elif key in ("current_goal", "current_task"):
                if not _hdr_task_done:
                    raw = "## TASK\n\n" + raw
                    _hdr_task_done = True
                elif key == "current_task":
                    raw = "### Task detail\n\n" + raw
            elif key in ("pinned_context", "memory", "knowledge_graph", "knowledge"):
                if not _hdr_ctx_done:
                    raw = "## CONTEXT\n\n" + raw
                    _hdr_ctx_done = True
            elif key == "agent_state":
                raw = "## SCRATCHPAD\n\n" + raw
        max_tok = budgets.get(key, 400)
        if key == "system_instructions":
            # Leave room for goal + workspace context if they exist.
            _need_goal = 1 if (sections.get("current_goal") or "").strip() else 0
            _need_state = 1 if (sections.get("agent_state") or "").strip() else 0
            _need_durable = 1 if (sections.get("durable_facts") or "").strip() else 0
            reserve = (
                (_reserve_current_goal if _need_goal else 0)
                + (_reserve_agent_state if _need_state else 0)
                + (_reserve_durable_facts if _need_durable else 0)
            )
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
        # Converge instead of giving up after one retry. truncate_to_tokens sizes its cut by a
        # chars-per-token RATIO, so on markdown/non-ASCII prose it routinely lands over the ask — and a
        # single `max_tok - 20` retry only closes a fixed 20 tokens of a proportional error. At the old
        # ~400-token section sizes the leftover overshoot was small enough to ignore; once a section is
        # budgeted ~900 (the capability manifest), the same 20% error is ~200 tokens, and it was being
        # stolen from `remaining` — which is exactly the room the NEXT sections were reserved. Measured:
        # system_instructions budgeted 895 came back 1092, leaving current_goal 7 tokens and chopping
        # "Current goal: refactor this module for me" mid-phrase.
        # Each pass scales the request by the overshoot ratio, so it converges in 2-3 rather than crawling.
        # Each pass scales the ASK by the overshoot it just produced, and is forced to strictly decrease.
        # Both halves matter: rescaling from the original max_tok instead of the current ask oscillates
        # rather than converges — measured 1321 -> 1415, then 1229 -> 1325, then 1309 -> 1405, ending
        # WORSE than it started and 76 tokens over budget, which is what stole the room reserved for
        # "Current goal: <the user's question>" and truncated it to "Current...".
        _ask = max_tok
        _attempts = 0
        while tok > max_tok and _attempts < 5:
            _attempts += 1
            _ask = max(24, min(_ask - 1, int(_ask * max_tok / max(tok, 1)) - 8))
            truncated = truncate_to_tokens(raw, _ask)
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
        merged_mem = "\n".join(deduped) if deduped else ""
        # Rebuild PRESERVING POSITION (audit #2): put the merged block where the FIRST memory section
        # was — keeping its canonical precedence BEFORE 'knowledge' (Reference docs) — and drop the other
        # memory slots. Appending merged_mem to the tail moved memory AFTER knowledge whenever a
        # knowledge_graph block existed, flipping precedence intermittently across turns.
        rebuilt: list = []
        placed = False
        for k, c in built:
            if k in memory_keys:
                if not placed and merged_mem:
                    rebuilt.append(("memory", merged_mem))
                    placed = True
                # otherwise drop this (now-merged) memory slot
            else:
                rebuilt.append((k, c))
        built = rebuilt

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

    record_prompt_metrics(metrics, n_ctx)

    # Phase 5: Record context pressure to Prometheus/fallback gauge
    try:
        from services.observability.prom_metrics import record_context_pressure
        pressure = metrics["total_tokens"] / max(1, total_budget)
        record_context_pressure(pressure)
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
