# -*- coding: utf-8 -*-
"""
memory_commands.py -- Inline memory command detection and execution.

Intercepts user messages that start with memory commands BEFORE they reach
the LLM, executes them directly against the DB, and returns a deterministic
response. Fast, reliable, no hallucination about what was stored.

Supported commands (case-insensitive, flexible phrasing):
    remember: <fact>         -- store to long-term memory
    forget: <text>           -- delete matching memories
    recall: <topic>          -- retrieve and show relevant memories
    memory status            -- count + recent memories
    memory clear --confirm   -- bulk delete (requires --confirm flag)

Returns MemoryCommandResult. If is_command=False, caller continues to LLM.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_REMEMBER_RE = re.compile(
    r"^(?:layla[,:]?\s+)?(?:remember|memorize|note|store|save)[:\s]+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_FORGET_RE = re.compile(
    r"^(?:layla[,:]?\s+)?(?:forget|delete|remove|unlearn)[:\s]+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_RECALL_RE = re.compile(
    r"^(?:layla[,:]?\s+)?(?:recall|what do you know about|what do you remember about|search memory)[:\s]+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_STATUS_RE = re.compile(
    r"^(?:layla[,:]?\s+)?memory\s+(?:status|stats|summary|count|how many)[\s?]*$",
    re.IGNORECASE,
)
_CLEAR_RE = re.compile(
    r"^(?:layla[,:]?\s+)?memory\s+clear\s*(--confirm)?[\s]*$",
    re.IGNORECASE,
)

_MIN_CONTENT_LEN = 8


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class MemoryCommandResult:
    is_command: bool = False
    response: str = ""
    command: str = ""
    items_affected: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_remember(content: str, aspect_id: str = "") -> MemoryCommandResult:
    content = content.strip()
    if len(content) < _MIN_CONTENT_LEN:
        return MemoryCommandResult(
            is_command=True, command="remember",
            response="Too short to be worth storing. Give me something specific.",
            error="too_short",
        )
    try:
        from services.memory_router import save_learning  # canonical write path
        row_id = save_learning(
            content=content,
            kind="user_fact",
            confidence=0.9,
            source="user_command",
            aspect_id=aspect_id or "",
        )
        if row_id == -1:
            return MemoryCommandResult(
                is_command=True, command="remember",
                response="Rate limit hit -- too many memories saved at once. Try again shortly.",
                error="rate_limited",
            )
        # Embed into vector store for semantic recall
        try:
            from layla.memory.vector_store import embed_and_store
            embed_and_store(content, metadata={"kind": "user_fact", "row_id": row_id})
        except Exception as _e:
            logger.debug("memory_commands: vector embed skipped: %s", _e)

        # Sync to working memory
        try:
            from services.working_memory import add_to_working_memory
            add_to_working_memory(content)
        except Exception as _e:
            logger.debug("memory_commands: working_memory update skipped: %s", _e)

        preview = content[:80] + ("..." if len(content) > 80 else "")
        return MemoryCommandResult(
            is_command=True, command="remember", items_affected=1,
            response=f'Stored: "{preview}"',
        )
    except Exception as e:
        logger.warning("memory_commands remember failed: %s", e)
        return MemoryCommandResult(
            is_command=True, command="remember",
            response=f"Failed to store: {e}", error=str(e),
        )


def _handle_forget(query: str, aspect_id: str = "") -> MemoryCommandResult:
    query = query.strip()
    if not query:
        return MemoryCommandResult(
            is_command=True, command="forget",
            response="Forget what? Give me a phrase to match against.",
        )
    try:
        from layla.memory.db import search_learnings_fts, delete_learnings_by_id, get_recent_learnings
        matches = search_learnings_fts(query, n=20, aspect_id=aspect_id or None)
        if not matches:
            recents = get_recent_learnings(n=200)
            ql = query.lower()
            matches = [r for r in recents if ql in (r.get("content") or "").lower()]

        if not matches:
            return MemoryCommandResult(
                is_command=True, command="forget", items_affected=0,
                response=f'Nothing found matching "{query}". Nothing deleted.',
            )

        ids = [r["id"] for r in matches if r.get("id")]
        delete_learnings_by_id(ids)

        previews = [r.get("content", "")[:60] for r in matches[:3]]
        preview_str = "\n".join(f"  - {p}..." for p in previews)
        more = f"\n  ... and {len(matches) - 3} more" if len(matches) > 3 else ""
        return MemoryCommandResult(
            is_command=True, command="forget", items_affected=len(ids),
            response=f'Deleted {len(ids)} memory/memories matching "{query}":\n{preview_str}{more}',
        )
    except Exception as e:
        logger.warning("memory_commands forget failed: %s", e)
        return MemoryCommandResult(
            is_command=True, command="forget",
            response=f"Failed to delete: {e}", error=str(e),
        )


def _handle_recall(query: str, aspect_id: str = "") -> MemoryCommandResult:
    query = query.strip()
    if not query:
        return MemoryCommandResult(
            is_command=True, command="recall",
            response="Recall what? Give me a topic or phrase.",
        )
    results = []
    try:
        from layla.memory.vector_store import search_memories_full
        results = search_memories_full(query, k=8, use_rerank=False)
    except Exception:
        pass
    if not results:
        try:
            from layla.memory.db import search_learnings_fts
            results = search_learnings_fts(query, n=8, aspect_id=aspect_id or None)
        except Exception as e:
            logger.warning("memory_commands recall failed: %s", e)
            return MemoryCommandResult(
                is_command=True, command="recall",
                response=f"Search failed: {e}", error=str(e),
            )

    if not results:
        return MemoryCommandResult(
            is_command=True, command="recall", items_affected=0,
            response=f'Nothing found in memory for "{query}".',
        )

    lines = []
    for i, r in enumerate(results[:8], 1):
        c = (r.get("content") or "").strip()
        conf = r.get("confidence") or r.get("score", 0)
        tag = f" [{conf:.0%}]" if conf else ""
        lines.append(f"{i}. {c[:120]}{tag}")

    return MemoryCommandResult(
        is_command=True, command="recall", items_affected=len(lines),
        response=f'Found {len(results)} memories for "{query}":\n\n' + "\n".join(lines),
    )


def _handle_status() -> MemoryCommandResult:
    try:
        from layla.memory.db import count_learnings, get_recent_learnings
        total = count_learnings()
        recents = get_recent_learnings(n=5)
        lines = [f"  - {r.get('content', '')[:80]}" for r in recents]
        recent_str = "\n".join(lines) if lines else "  (none yet)"
        return MemoryCommandResult(
            is_command=True, command="status",
            response=f"Memory: {total} total learnings stored.\n\nMost recent:\n{recent_str}",
            items_affected=total,
        )
    except Exception as e:
        return MemoryCommandResult(
            is_command=True, command="status",
            response=f"Could not read memory stats: {e}", error=str(e),
        )


def _handle_clear(confirmed: bool) -> MemoryCommandResult:
    if not confirmed:
        return MemoryCommandResult(
            is_command=True, command="clear",
            response=(
                "This will delete ALL stored memories permanently.\n"
                "To confirm: `memory clear --confirm`"
            ),
        )
    try:
        from layla.memory.db import _conn
        conn = _conn()
        deleted = conn.execute("DELETE FROM learnings").rowcount
        conn.commit()
        return MemoryCommandResult(
            is_command=True, command="clear", items_affected=deleted,
            response=f"Cleared {deleted} memories. Fresh start.",
        )
    except Exception as e:
        return MemoryCommandResult(
            is_command=True, command="clear",
            response=f"Clear failed: {e}", error=str(e),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_and_handle(message: str, aspect_id: str = "") -> MemoryCommandResult:
    """
    Check if message is a memory command. Execute it if so.
    Returns MemoryCommandResult with is_command=True if handled.
    If is_command=False, caller should continue to normal LLM path.
    """
    msg = (message or "").strip()
    if not msg:
        return MemoryCommandResult(is_command=False)

    m = _REMEMBER_RE.match(msg)
    if m:
        return _handle_remember(m.group(1), aspect_id=aspect_id)

    m = _FORGET_RE.match(msg)
    if m:
        return _handle_forget(m.group(1), aspect_id=aspect_id)

    m = _RECALL_RE.match(msg)
    if m:
        return _handle_recall(m.group(1), aspect_id=aspect_id)

    if _STATUS_RE.match(msg):
        return _handle_status()

    m = _CLEAR_RE.match(msg)
    if m:
        return _handle_clear(confirmed=bool(m.group(1)))

    return MemoryCommandResult(is_command=False)
