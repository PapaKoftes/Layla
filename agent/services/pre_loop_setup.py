"""Pre-loop setup helpers extracted from agent_loop._autonomous_run_impl_core.

These functions handle deterministic early-exit checks and context preparation
that run before the main tool loop begins.  They have no dependency on
agent_loop globals, so they can be imported directly.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("layla.pre_loop_setup")


# ---------------------------------------------------------------------------
# Fast-path early exits
# ---------------------------------------------------------------------------

def check_memory_command(goal: str, aspect_id: str = "") -> dict | None:
    """Detect and handle memory commands (teach/forget/recall) before LLM.

    Returns a complete state dict if the goal is a memory command (caller
    should return it immediately), or ``None`` to continue normal processing.
    """
    try:
        import orchestrator
        from services.memory_commands import detect_and_handle as _mem_detect

        result = _mem_detect(goal, aspect_id=aspect_id or "")
        if result.is_command:
            active_asp = orchestrator.select_aspect(goal, force_aspect=aspect_id)
            # Lazy import to access goal context vars
            from agent_loop import _goal_optimized_var, _goal_original_var
            _go = _goal_original_var.get() or goal
            return {
                "goal": goal,
                "original_goal": _go,
                "goal_original": _go,
                "goal_optimized": _goal_optimized_var.get() or "",
                "objective": goal,
                "objective_complete": True,
                "depth": 0,
                "steps": [{
                    "action": "memory_command",
                    "result": result.response,
                    "deliberated": False,
                    "aspect": active_asp.get("id", "layla"),
                }],
                "status": "finished",
                "start_time": time.time(),
                "tool_calls": 0,
                "aspect": active_asp.get("id", "layla"),
                "aspect_name": active_asp.get("name", "Layla"),
                "refused": False,
                "refusal_reason": "",
                "last_verification": None,
                "consecutive_no_progress": 0,
                "environment_aligned": None,
                "last_tool_used": None,
                "strategy_shift_count": 0,
                "priority_level": None,
                "impact_estimate": None,
                "effort_estimate": None,
                "risk_estimate": None,
                "ux_states": [],
                "memory_influenced": [],
                "cited_knowledge_sources": [],
                "sub_goals": [],
                "reflection_pending": False,
                "reflection_asked": False,
                "reasoning_mode": "none",
                "memory_command": result.command,
                "memory_items_affected": result.items_affected,
            }
    except Exception as _err:
        logger.debug("memory_commands intercept failed: %s", _err)
    return None


def extract_working_memory(goal: str) -> None:
    """Passive working-memory extraction from the user's message."""
    try:
        from services.working_memory import auto_extract_from_message as _wm_extract
        _wm_extract(goal)
    except Exception as _err:
        logger.debug("working_memory extract failed: %s", _err)


def check_content_guard(goal: str, aspect_id: str = "") -> dict | None:
    """Deterministic pre-model filter for universally harmful content.

    Returns a complete state dict if blocked, or ``None`` to continue.
    """
    try:
        import runtime_safety
        from services.content_guard import blocked_response as _cg_msg
        from services.content_guard import check_input as _cg_check

        cfg = runtime_safety.load_config()
        result = _cg_check(goal, cfg)
        if result.blocked:
            logger.warning("content_guard: blocked tier=%d cat=%s", result.tier, result.category)
            return {
                "goal": goal,
                "objective": goal,
                "objective_complete": True,
                "depth": 0,
                "steps": [{"action": "content_guard", "result": _cg_msg(result), "deliberated": False}],
                "status": "blocked",
                "start_time": time.time(),
                "tool_calls": 0,
                "aspect": aspect_id or "layla",
                "aspect_name": "Layla",
                "refused": True,
                "refusal_reason": f"content_guard_tier{result.tier}",
                "last_verification": None,
                "consecutive_no_progress": 0,
                "original_goal": goal,
                "goal_original": goal,
                "goal_optimized": "",
                "ux_states": [],
                "memory_influenced": [],
                "cited_knowledge_sources": [],
                "sub_goals": [],
                "reasoning_mode": "none",
            }
    except Exception as _err:
        logger.debug("content_guard check failed: %s", _err)
    return None


def check_dignity(goal: str) -> str:
    """Detect abuse and return a boundary prompt for injection (or empty string)."""
    try:
        import runtime_safety
        from services.dignity_engine import analyze_and_get_prompt as _dignity_check

        cfg = runtime_safety.load_config()
        return _dignity_check(goal, cfg)
    except Exception as _err:
        logger.debug("dignity_engine check failed: %s", _err)
    return ""


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------

def build_precomputed_recall(
    goal: str,
    cfg: dict,
    workspace_root: str,
    reasoning_mode: str,
    context_files: list[str] | None = None,
    aspect_id: str = "",
) -> tuple[dict | None, str, list[str]]:
    """Build the pre-computed semantic recall and packed context for a run.

    Returns ``(packed_context_dict_or_None, recall_text, memory_influenced_list)``.
    """
    _packed_ctx: dict | None = None
    _precomputed_recall = ""
    memory_influenced: list[str] = []

    if goal and reasoning_mode != "none":
        # Invalidate stale semantic index when workspace files changed
        _ws = (str(workspace_root).strip() if workspace_root else "") or str(cfg.get("sandbox_root") or "")
        if _ws:
            try:
                from services.workspace_index import invalidate_if_changed
                invalidate_if_changed(_ws)
            except Exception:
                pass

        try:
            from services.context_builder import build_context

            wr = (str(workspace_root).strip() if workspace_root else "") or str(cfg.get("sandbox_root") or "")
            _packed_ctx = build_context(
                goal,
                {
                    "workspace_root": wr,
                    "context_files": list(context_files or []),
                    "reasoning_mode": reasoning_mode,
                    "k_memory": int(cfg.get("semantic_k", 5)),
                    "k_code": int(cfg.get("context_builder_code_k", 5)),
                },
            )
            _precomputed_recall = (_packed_ctx.get("memory_recall_text") or "").strip()
        except Exception as _err:
            logger.debug("context_builder failed: %s", _err)
            try:
                from services.system_head_builder import semantic_recall as _semantic_recall
                _precomputed_recall = _semantic_recall(goal, k=cfg.get("semantic_k", 5)).strip()
            except Exception:
                _precomputed_recall = ""

    # Check memory sources
    try:
        from services.system_head_builder import load_learnings as _load_learnings
        if _load_learnings(aspect_id=aspect_id).strip():
            memory_influenced.append("learnings")
    except Exception:
        pass
    if _precomputed_recall:
        memory_influenced.append("semantic_recall")

    return _packed_ctx, _precomputed_recall, memory_influenced
