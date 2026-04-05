"""
agent/core/observer.py — Phase 1: Observe

Assembles a stable, versioned context snapshot (ObserveSnapshot) before
any planning or tool execution begins. The snapshot is frozen at observe time —
nothing outside it should influence the planner.

Extracted from agent_loop._build_system_head() and related helpers.
agent_loop.py delegates here; backward compatibility is preserved.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("layla")


def build_snapshot(
    goal: str,
    conversation_id: str,
    cfg: dict,
    aspect_id: str = "",
    conversation_history: list | None = None,
    workspace_root: str = "",
    allow_write: bool = False,
    allow_run: bool = False,
) -> dict[str, Any]:
    """
    Build an ObserveSnapshot for a single autonomous_run invocation.

    Returns a dict with all context needed by the planner:
      goal, conversation_id, aspect_id, n_ctx, config_snapshot,
      retrieved_memories, retrieved_knowledge, project_context,
      budget_map, observed_at

    All DB / vector reads happen here. The planner receives a frozen copy.
    """
    import time as _time
    observed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Resolve n_ctx from config
    n_ctx = int(cfg.get("n_ctx", 4096) or 4096)

    # Compute proportional token budgets for this n_ctx
    budget_map: dict[str, int] = {}
    try:
        from services.context_budget import get_budgets
        budget_map = get_budgets(n_ctx)
    except Exception as e:
        logger.debug("observer: get_budgets failed: %s", e)

    # Retrieve memories (FTS + vector, non-blocking on failure)
    retrieved_memories: list[str] = []
    try:
        from layla.memory.db import search_learnings_fts
        rows = search_learnings_fts(goal[:200], n=cfg.get("learnings_n", 15))
        retrieved_memories = [r.get("content", "") for r in rows if r.get("content")]
    except Exception as e:
        logger.debug("observer: FTS recall failed: %s", e)

    # Vector recall — optional, skip if ChromaDB unavailable
    try:
        from layla.memory.vector_store import search_memories_full
        vresults = search_memories_full(goal[:200], k=5, use_rerank=False)
        for r in vresults:
            c = r.get("content", "")
            if c and c not in retrieved_memories:
                retrieved_memories.append(c)
    except Exception as e:
        logger.debug("observer: vector recall failed: %s", e)

    # Project context
    project_context: dict = {}
    try:
        from layla.memory.db import get_project_context
        project_context = get_project_context() or {}
    except Exception:
        pass

    # Conversation history — use provided or fall back to global history
    history = list(conversation_history or [])

    return {
        "goal": goal,
        "conversation_id": conversation_id,
        "aspect_id": aspect_id or "morrigan",
        "n_ctx": n_ctx,
        "config_snapshot": dict(cfg),  # frozen copy
        "budget_map": budget_map,
        "retrieved_memories": retrieved_memories,
        "retrieved_knowledge": [],   # populated by agent_loop._load_knowledge_docs
        "project_context": project_context,
        "conversation_history": history,
        "workspace_root": workspace_root,
        "allow_write": allow_write,
        "allow_run": allow_run,
        "observed_at": observed_at,
        "observe_version": 1,
    }
