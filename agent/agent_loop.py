import json
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

# Goal preservation: the prompt optimizer (in `autonomous_run`) may rewrite the
# user's goal before downstream processing. We must keep the canonical original
# text available so memory writes, reflection, and trace endpoints can refer to
# what the user actually said. These contextvars are set in `autonomous_run`
# right after capturing/optimizing the goal and read by `_autonomous_run_impl_core`.
# BL-121: the vars + accessors now live in services.agent.goal_context (a neutral
# module) so services don't import agent_loop privates; re-exported here for back-compat.
from services.agent.goal_context import (  # noqa: E402,F401
    _goal_optimized_var,
    _goal_original_var,
    get_last_goal_optimized,
    get_last_goal_original,
)

logger = logging.getLogger("layla")

import orchestrator  # noqa: E402
import runtime_safety  # noqa: E402
from core.executor import run_tool as _run_tool  # noqa: E402
from decision_schema import parse_decision as _parse_decision  # noqa: E402
from layla.memory.db import get_aspect_memories as _db_get_aspect_memories  # noqa: E402
from layla.memory.db import get_recent_learnings as _db_get_learnings  # noqa: E402

# NOTE: _db_migrate import removed — migration runs once in main.py lifespan.
from layla.tools.registry import TOOLS, set_effective_sandbox  # noqa: E402
from services.agent.intent_classifier import (
    _extract_file_and_content,
    _extract_path,
    _extract_shell_argv,
    classify_intent,
)
from services.agent.llm_decision import (
    format_recovery_hint_for_prompt as _format_recovery_hint_for_prompt_impl,
)
from services.agent.llm_decision import (
    get_tools_for_goal as _get_tools_for_goal_impl,
)
from services.agent.llm_decision import (
    llm_decision as _llm_decision_impl,
)
from services.agent.postchecks import (
    _edit_tool_lint_path,
    _run_auto_lint_test_fix,
    _run_git_auto_commit,
)
from services.agent.probe_helpers import (
    apply_probe_guidance as _apply_probe_guidance_impl,
)
from services.agent.probe_helpers import (
    maybe_preprobe_file as _maybe_preprobe_file_impl,
)
from services.agent.probe_helpers import (
    probe_store as _probe_store_impl,
)
from services.agent.step_formatting import (
    VALID_TOOLS as _VALID_TOOLS,
)
from services.agent.step_formatting import (
    format_steps as _format_steps,
)
from services.agent.step_formatting import (
    summarize_steps_deterministic as _summarize_steps_deterministic,
)
from services.context.context_manager import DEFAULT_BUDGETS, build_system_prompt  # noqa: E402
from services.context.context_window_ux import emit_context_window_ux
from services.infrastructure.outcome_writer import (  # noqa: E402
    _auto_extract_learnings,
    _extract_patch_text,
    _maybe_save_echo_memory,
    _save_outcome_memory,
)
from services.infrastructure.output_polish import polish_output as _polish_output  # noqa: E402
from services.infrastructure.resource_manager import (  # noqa: E402
    PRIORITY_AGENT,
    PRIORITY_CHAT,
    classify_load,
    schedule_slot,
)
from services.llm.llm_gateway import get_stop_sequences, llm_serialize_lock, run_completion  # noqa: E402
from services.safety.agent_safety import (  # noqa: E402
    maybe_planning_strict_refusal as _maybe_planning_strict_refusal,
)
from services.safety.agent_safety import (
    maybe_step_tool_allowlist_refusal as _maybe_step_tool_allowlist_refusal,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = Path(__file__).resolve().parent
RESEARCH_LAB_ROOT = AGENT_DIR / ".research_lab"

# ---------------------------------------------------------------------------
# System head builder: extracted to services/system_head_builder.py
# These imports maintain backward compatibility for internal callers.
# ---------------------------------------------------------------------------
from services.agent.approval_helpers import (
    _admin_pre_mutate,
    _approval_preview_diff,
    _has_any_grant,
    _write_pending,
)
from services.agent.response_builder import (
    clean_response_text as _clean_response_text_impl,
)

# ---------------------------------------------------------------------------
# Phase 2 decomposition: delegated modules under services/agent/
# ---------------------------------------------------------------------------
from services.agent.response_builder import (
    is_junk_reply as _is_junk_reply_impl,
)
from services.agent.response_builder import (
    is_self_contained_question as _is_self_contained_question,
)
from services.agent.response_builder import (
    iter_with_response_pacing as _iter_with_response_pacing_impl,
)
from services.agent.response_builder import (
    looks_like_raw_tool_dict as _looks_like_raw_tool_dict,
)
from services.agent.response_builder import (
    quick_reply_for_trivial_turn as _quick_reply_for_trivial_turn_impl,
)
from services.agent.response_builder import (
    strip_junk_from_reply as _strip_junk_from_reply_impl,
)
from services.agent.response_builder import (
    synthesize_direct_answer as _synthesize_direct_answer,
)
from services.agent.response_builder import (
    truncate_at_next_user_turn as _truncate_at_next_user_turn_impl,
)
from services.agent.run_finalizer import (
    finalize_run_state as _finalize_run_state_impl,
)

# ---------------------------------------------------------------------------
# Streaming handler: extracted to services/agent/stream_handler.py
# ---------------------------------------------------------------------------
from services.agent.stream_handler import (
    _stream_reason_body as _stream_reason_body_impl,
)
from services.agent.stream_handler import (
    stream_reason as _stream_reason_impl,
)
from services.agent.tool_guards import (
    run_tool_guards as _run_tool_guards_impl,
)
from services.agent.tool_helpers import (
    apply_lite_mode_overrides as _apply_lite_mode_overrides_impl,
)
from services.agent.tool_helpers import (
    get_effective_config as _get_effective_config_impl,
)
from services.agent.tool_helpers import (
    inject_cancel_message as _inject_cancel_message_impl,
)
from services.agent.tool_helpers import (
    inject_workspace_args as _inject_workspace_args_impl,
)
from services.agent.tool_helpers import (
    normalize_mcp_tool_args as _normalize_mcp_tool_args_impl,
)
from services.agent.tool_helpers import (
    path_under_lab as _path_under_lab_impl,
)
from services.agent.tool_helpers import (
    register_exact_tool_call as _register_exact_tool_call_impl,
)
from services.agent.tool_helpers import (
    research_response_asks_user as _research_response_asks_user_impl,
)
from services.agent.ux_emitter import (
    BackgroundProgressSteps as _BackgroundProgressSteps_impl,
)
from services.agent.ux_emitter import (
    emit_context_window_ux as _emit_context_window_ux_impl,
)
from services.agent.ux_emitter import (
    emit_tool_start as _emit_tool_start_impl,
)
from services.agent.ux_emitter import (
    emit_tool_step as _emit_tool_step_impl,
)
from services.agent.ux_emitter import (
    emit_ux as _emit_ux_impl,
)
from services.agent.ux_emitter import (
    summarize_tool_result as _summarize_tool_result_impl,
)
from services.agent.verification_engine import (
    SKIP_TOOL_OUTPUT_VALIDATION as _SKIP_TOOL_OUTPUT_VALIDATION_IMPL,
)
from services.agent.verification_engine import (
    VERIFY_TOOLS as _VERIFY_TOOLS_IMPL,
)
from services.agent.verification_engine import (
    apply_deterministic_tool_verification as _apply_deterministic_tool_verification_impl,
)
from services.agent.verification_engine import (
    log_tool_outcome as _log_tool_outcome_impl,
)
from services.agent.verification_engine import (
    maybe_validate_tool_output as _maybe_validate_tool_output_impl,
)
from services.agent.verification_engine import (
    observe_environment as _observe_environment_impl,
)
from services.agent.verification_engine import (
    run_edit_postchecks as _run_edit_postchecks_impl,
)
from services.agent.verification_engine import (
    run_verification_after_tool as _run_verification_after_tool_impl,
)
from services.agent.verification_engine import (
    verify_tool_progress as _verify_tool_progress_impl,
)
from services.prompts.system_head_builder import (
    append_persona_focus_to_personality as _append_persona_focus_to_personality,
)
from services.prompts.system_head_builder import (
    aspect_dict_by_id as _aspect_dict_by_id,
)
from services.prompts.system_head_builder import (
    build_expertise_domain_block as _build_expertise_domain_block,
)
from services.prompts.system_head_builder import (  # noqa: E402
    build_system_head as _build_system_head,
)
from services.prompts.system_head_builder import (
    decompose_goal as _decompose_goal,
)
from services.prompts.system_head_builder import (
    enrich_deliberation_context as _enrich_deliberation_context,
)
from services.prompts.system_head_builder import (
    extract_aspect_domain_keywords as _extract_aspect_domain_keywords,
)
from services.prompts.system_head_builder import (
    get_repo_structure as _get_repo_structure,
)
from services.prompts.system_head_builder import (
    is_lightweight_chat_turn as _is_lightweight_chat_turn,
)
from services.prompts.system_head_builder import (
    load_learnings as _load_learnings,
)
from services.prompts.system_head_builder import (
    needs_graph as _needs_graph,
)
from services.prompts.system_head_builder import (
    needs_knowledge_rag as _needs_knowledge_rag,
)
from services.prompts.system_head_builder import (
    relationship_codex_context as _relationship_codex_context,
)
from services.prompts.system_head_builder import (
    semantic_recall as _semantic_recall,
)
from services.tools.tool_dispatch import (
    DispatchContext as _DispatchContext,
)
from services.tools.tool_dispatch import (
    DispatchResult as _DispatchResult,
)

# ---------------------------------------------------------------------------
# Tool dispatch: extracted to services/tool_dispatch.py
# Import here for backward compatibility and to ensure the module is loadable.
# ---------------------------------------------------------------------------
from services.tools.tool_dispatch import (  # noqa: E402
    dispatch_tool_intent as _dispatch_tool_intent,
)

# ---------------------------------------------------------------------------
# Backward-compat aliases — pure passthroughs to extracted modules.
# Tests and callers that reference agent_loop._X still work.
# ---------------------------------------------------------------------------
_SKIP_TOOL_OUTPUT_VALIDATION = _SKIP_TOOL_OUTPUT_VALIDATION_IMPL
_BackgroundProgressSteps = _BackgroundProgressSteps_impl
_log_tool_outcome = _log_tool_outcome_impl
_maybe_validate_tool_output = _maybe_validate_tool_output_impl
_apply_deterministic_tool_verification = _apply_deterministic_tool_verification_impl
_normalize_mcp_tool_args = _normalize_mcp_tool_args_impl
_inject_workspace_args = _inject_workspace_args_impl
_inject_cancel_message = _inject_cancel_message_impl
_register_exact_tool_call = _register_exact_tool_call_impl
_apply_lite_mode_overrides = _apply_lite_mode_overrides_impl
_path_under_lab = _path_under_lab_impl
_research_response_asks_user = _research_response_asks_user_impl


def _get_effective_config(base_cfg: dict) -> dict:
    """Apply system_optimizer runtime overrides. Never persists to disk."""
    return _apply_lite_mode_overrides(_get_effective_config_impl(base_cfg))


# Placeholder for sanitized assistant turns in convo_block (never use "I replied." ÃÃÃ¶ model repeats it)
_SANITIZED_PLACEHOLDER = "[...]"

# UX interaction states (UI layer only; no change to decision logic)
UX_STATE_THINKING = "thinking"
UX_STATE_VERIFYING = "verifying"
UX_STATE_CHANGING_APPROACH = "changing_approach"
UX_STATE_REFRAMING_OBJECTIVE = "reframing_objective"


_emit_ux = _emit_ux_impl
_emit_tool_start = _emit_tool_start_impl
_summarize_tool_result = _summarize_tool_result_impl
_emit_tool_step = _emit_tool_step_impl


def _emit_context_window_ux(
    ux_state_queue: queue.Queue | None,
    conversation_history: list | None,
    cfg: dict,
    state: dict,
) -> None:
    """Delegate to services.agent.ux_emitter (keeps call sites stable)."""
    return _emit_context_window_ux_impl(ux_state_queue, conversation_history, cfg, state, format_steps_fn=_format_steps)


# _approval_preview_diff: moved to services/agent/approval_helpers.py
# Imported above.


_is_junk_reply = _is_junk_reply_impl
_quick_reply_for_trivial_turn = _quick_reply_for_trivial_turn_impl
truncate_at_next_user_turn = _truncate_at_next_user_turn_impl
strip_junk_from_reply = _strip_junk_from_reply_impl
_clean_response_text = _clean_response_text_impl


# Cross-request reasoning-mode smoothing -- shared with the streaming path.
from services.agent.reasoning_state import (
    get as _rstate_get,
)
from services.agent.reasoning_state import (
    get_lock as _rstate_get_lock,
)
from services.agent.reasoning_state import (
    set_ as _rstate_set,
)

_reason_mode_lock = _rstate_get_lock()
_load_lock = threading.Lock()


_iter_with_response_pacing = _iter_with_response_pacing_impl
stream_reason = _stream_reason_impl
_stream_reason_body = _stream_reason_body_impl
_last_cpu: float = 0.0
_last_ram: float = 0.0


def system_overloaded(priority: int = PRIORITY_AGENT) -> bool:
    global _last_cpu, _last_ram
    cfg = runtime_safety.load_config()  # noqa: F841
    cpu = psutil.cpu_percent(interval=0)
    ram = psutil.virtual_memory().percent
    with _load_lock:
        # Smooth with previous sample so a single spike does not block
        smooth_cpu = (cpu + _last_cpu) / 2.0 if _last_cpu else cpu
        smooth_ram = (ram + _last_ram) / 2.0 if _last_ram else ram
        _last_cpu, _last_ram = cpu, ram
    # Chat should remain reactive even under pressure; background can be throttled.
    if priority <= PRIORITY_CHAT:
        return False
    # These keys aren't in the coerce/clamp schema, so a hand-edited null/string reaches float() raw and
    # would crash the governor on a background task. Coerce safely to the default.
    def _f(v, default: float) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
    hard_cpu = _f(cfg.get("hard_cpu_percent", cfg.get("max_cpu_percent", 95)), 95.0)
    hard_ram = _f(cfg.get("max_ram_percent", 90), 90.0)
    return smooth_cpu > hard_cpu or smooth_ram > hard_ram


# _VALID_TOOLS, _format_steps, _summarize_steps_deterministic: moved to
# services/agent/step_formatting.py. Imported above.


def _get_tools_for_goal(goal: str, *, context: str = "", workspace_root: str = "", state: dict | None = None) -> frozenset:
    """Thin wrapper -- delegates to services.agent.llm_decision."""
    return _get_tools_for_goal_impl(
        goal, context=context, workspace_root=workspace_root, state=state,
        tools_registry=TOOLS, valid_tools_all=_VALID_TOOLS,
    )


_probe_store = _probe_store_impl
_maybe_preprobe_file = _maybe_preprobe_file_impl
_apply_probe_guidance = _apply_probe_guidance_impl

# Tools that get a self-verification step (delegated constant from verification_engine)
_VERIFY_TOOLS = _VERIFY_TOOLS_IMPL


_verify_tool_progress = _verify_tool_progress_impl
_observe_environment = _observe_environment_impl
_format_recovery_hint_for_prompt = _format_recovery_hint_for_prompt_impl


def _classify_failure_and_recovery(state: dict) -> None:
    from services.infrastructure.failure_recovery import classify_failure_and_recovery
    classify_failure_and_recovery(state)


def _run_edit_postchecks(
    state: dict,
    intent: str,
    raw_result: object,
    *,
    workspace: str,
    cfg: dict,
    re_execute: Callable[[], object] | None = None,
) -> tuple[object, bool, str]:
    """Validate tool output, deterministic verification, optional single retry."""
    return _run_edit_postchecks_impl(state, intent, raw_result, workspace=workspace, cfg=cfg, re_execute=re_execute)


def _run_verification_after_tool(state: dict, tool_name: str, result: dict, workspace: str = "") -> None:
    """If tool is verifiable and succeeded, run verification and environment observation; update state."""
    return _run_verification_after_tool_impl(state, tool_name, result, workspace, format_steps_fn=_format_steps)


def _llm_decision(
    goal: str,
    state: dict,
    context: str,
    active_aspect: dict,
    show_thinking: bool,
    conversation_history: list,
) -> dict | None:
    """Thin wrapper -- delegates to services.agent.llm_decision."""
    return _llm_decision_impl(
        goal, state, context, active_aspect, show_thinking, conversation_history,
        format_steps_fn=_format_steps,
        tools_registry=TOOLS,
        valid_tools_all=_VALID_TOOLS,
    )


# ---------------------------------------------------------------------------
# Intent classification & goal-text extraction helpers:
#   classify_intent, _extract_path, _extract_file_and_content, _extract_shell_argv
# Moved to services.agent.intent_classifier (imported at top of file).
# ---------------------------------------------------------------------------


def _autonomous_run_serialize_lock(workspace_root: str):
    """Serialize agent flights: global lock by default; optional per-workspace when configured."""
    if runtime_safety.load_config().get("llm_serialize_per_workspace"):
        from services.llm.llm_gateway import _resolve_workspace_lock_key, get_agent_serialize_lock

        return get_agent_serialize_lock(_resolve_workspace_lock_key(workspace_root))
    return llm_serialize_lock


# ---------------------------------------------------------------------------
# P2-5: AgentRunRequest dataclass – bundles all autonomous_run parameters
# into a single typed object for cleaner call-sites. The existing
# autonomous_run() signature is unchanged; use autonomous_run_from_request()
# when you want to pass a dataclass instead.
# ---------------------------------------------------------------------------

@dataclass
class AgentRunRequest:
    """Encapsulates all parameters for an agent run.

    Every field mirrors a parameter of :func:`autonomous_run` with the same
    default value.  Pass an instance to :func:`autonomous_run_from_request`
    to invoke the agent loop.
    """

    goal: str = ""
    context: str = ""
    workspace_root: str = ""
    allow_write: bool = False
    allow_run: bool = False
    conversation_history: list = field(default=None)
    aspect_id: str = ""
    show_thinking: bool = False
    stream_final: bool = False
    ux_state_queue: queue.Queue | None = None
    research_mode: bool = False
    plan_depth: int = 0
    model_override: str | None = None
    reasoning_effort: str | None = None
    priority: int = PRIORITY_AGENT
    persona_focus: str = ""
    conversation_id: str = ""
    cognition_workspace_roots: list[str] | None = None
    client_abort_event: threading.Event | None = None
    background_progress_callback: Callable[[dict], None] | None = None
    active_plan_id: str = ""
    plan_approved: bool = False
    fabrication_assist_runner_request: str = ""
    resume_execution_state: dict | None = None
    coordinator_trace: dict | None = None
    # keyword-only parameters in autonomous_run()
    engineering_pipeline_mode: str = "chat"
    clarification_reply: str = ""
    skip_engineering_pipeline: bool = False
    context_files: list[str] | None = None


def autonomous_run_from_request(request: AgentRunRequest) -> dict:
    """Call autonomous_run() from a dataclass request.

    This is a backward-compatible convenience wrapper: the underlying
    :func:`autonomous_run` function signature is unchanged, so callers
    that already pass keyword arguments continue to work.
    """
    return autonomous_run(
        goal=request.goal,
        context=request.context,
        workspace_root=request.workspace_root,
        allow_write=request.allow_write,
        allow_run=request.allow_run,
        conversation_history=request.conversation_history,
        aspect_id=request.aspect_id,
        show_thinking=request.show_thinking,
        stream_final=request.stream_final,
        ux_state_queue=request.ux_state_queue,
        research_mode=request.research_mode,
        plan_depth=request.plan_depth,
        model_override=request.model_override,
        reasoning_effort=request.reasoning_effort,
        priority=request.priority,
        persona_focus=request.persona_focus,
        conversation_id=request.conversation_id,
        cognition_workspace_roots=request.cognition_workspace_roots,
        client_abort_event=request.client_abort_event,
        background_progress_callback=request.background_progress_callback,
        active_plan_id=request.active_plan_id,
        plan_approved=request.plan_approved,
        fabrication_assist_runner_request=request.fabrication_assist_runner_request,
        resume_execution_state=request.resume_execution_state,
        coordinator_trace=request.coordinator_trace,
        engineering_pipeline_mode=request.engineering_pipeline_mode,
        clarification_reply=request.clarification_reply,
        skip_engineering_pipeline=request.skip_engineering_pipeline,
        context_files=request.context_files,
    )


def autonomous_run(
    goal: str,
    context: str = "",
    workspace_root: str = "",
    allow_write: bool = False,
    allow_run: bool = False,
    conversation_history: list = None,
    aspect_id: str = "",
    show_thinking: bool = False,
    stream_final: bool = False,
    ux_state_queue: queue.Queue | None = None,
    research_mode: bool = False,
    plan_depth: int = 0,
    model_override: str | None = None,
    reasoning_effort: str | None = None,
    priority: int = PRIORITY_AGENT,
    persona_focus: str = "",
    conversation_id: str = "",
    cognition_workspace_roots: list[str] | None = None,
    client_abort_event: threading.Event | None = None,
    background_progress_callback: Callable[[dict], None] | None = None,
    active_plan_id: str = "",
    plan_approved: bool = False,
    fabrication_assist_runner_request: str = "",
    resume_execution_state: dict | None = None,
    coordinator_trace: dict | None = None,
    *,
    engineering_pipeline_mode: str = "chat",
    clarification_reply: str = "",
    skip_engineering_pipeline: bool = False,
    context_files: list[str] | None = None,
) -> dict:
    # Prompt optimizer: enhance user goal before processing (graceful; never blocks)
    # Preserve the original user-authored goal text so downstream code can refer to
    # the canonical words even when the optimizer rewrites the prompt.
    goal_original = goal
    goal_optimized: str | None = None
    try:
        from services.prompts.prompt_optimizer import optimize as _opt_goal
        _cfg_now = runtime_safety.load_config() if hasattr(runtime_safety, "load_config") else {}
        if _cfg_now.get("prompt_optimizer_enabled", True):
            _opt_result = _opt_goal(
                goal,
                context={
                    "aspect": aspect_id or "",
                    "workspace": str(workspace_root or ""),
                },
            )
            if _opt_result.get("changed") and _opt_result.get("optimized"):
                logger.debug(
                    "prompt_optimizer: [%s] goal rewritten (tier=%d)",
                    _opt_result.get("intent", "?"), _opt_result.get("tier", 0),
                )
                goal_optimized = _opt_result["optimized"]
                goal = _opt_result["optimized"]
    except Exception as _opt_e:
        logger.debug("prompt_optimizer inject failed: %s", _opt_e)

    # Phase B Fix 2: publish canonical pre/post-optimizer goal text via contextvars
    # so downstream code (state, /health/trace, memory writes) can refer to the
    # text the user actually authored. Tokens are reset in the finally below.
    _goal_orig_token = _goal_original_var.set(goal_original or "")
    _goal_opt_token = _goal_optimized_var.set(goal_optimized or "")

    # Phase 4.3: set per-task context vars for structured log isolation
    try:
        import uuid as _uuid

        from services.infrastructure.task_context import reset_task_context, set_task_context
        _tid = conversation_id or str(_uuid.uuid4())[:8]
        _ctx_tokens = set_task_context(
            workspace=str(workspace_root or ""),
            aspect=str(aspect_id or ""),
            task_id=_tid,
        )
    except Exception as e:
        logger.debug("task_context setup failed: %s", e, exc_info=True)
        _ctx_tokens = None
    try:
        with schedule_slot(priority=priority):
            with _autonomous_run_serialize_lock(workspace_root):
                return _autonomous_run_impl(
                    goal, context, workspace_root, allow_write, allow_run,
                    conversation_history, aspect_id, show_thinking, stream_final,
                    ux_state_queue, research_mode, plan_depth, model_override, reasoning_effort, priority,
                    persona_focus,
                    conversation_id,
                    cognition_workspace_roots,
                    client_abort_event,
                    background_progress_callback,
                    active_plan_id,
                    plan_approved,
                    fabrication_assist_runner_request=fabrication_assist_runner_request,
                    resume_execution_state=resume_execution_state,
                    coordinator_trace=coordinator_trace,
                    engineering_pipeline_mode=engineering_pipeline_mode,
                    clarification_reply=clarification_reply,
                    skip_engineering_pipeline=skip_engineering_pipeline,
                    context_files=context_files,
                )
    except RuntimeError as e:
        if "system_busy" in str(e):
            active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
            return {
                "status": "system_busy",
                "steps": [],
                "aspect": active_aspect.get("id", "layla"),
                "aspect_name": active_aspect.get("name", "Layla"),
                "refused": False,
                "refusal_reason": "",
                "ux_states": [],
                "memory_influenced": [],
                "reasoning_mode": "light",
            }
        raise
    finally:
        if _ctx_tokens is not None:
            try:
                reset_task_context(_ctx_tokens)
            except Exception as e:
                logger.debug("agent_loop: %s", e)
        try:
            _goal_original_var.reset(_goal_orig_token)
            _goal_optimized_var.reset(_goal_opt_token)
        except Exception as e:
            logger.debug("agent_loop: %s", e)


def _autonomous_run_impl(
    goal: str,
    context: str,
    workspace_root: str,
    allow_write: bool,
    allow_run: bool,
    conversation_history: list,
    aspect_id: str,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue: queue.Queue | None,
    research_mode: bool,
    plan_depth: int = 0,
    model_override: str | None = None,
    reasoning_effort: str | None = None,
    priority: int = PRIORITY_AGENT,
    persona_focus: str = "",
    conversation_id: str = "",
    cognition_workspace_roots: list[str] | None = None,
    client_abort_event: threading.Event | None = None,
    background_progress_callback: Callable[[dict], None] | None = None,
    active_plan_id: str = "",
    plan_approved: bool = False,
    fabrication_assist_runner_request: str = "",
    resume_execution_state: dict | None = None,
    coordinator_trace: dict | None = None,
    *,
    engineering_pipeline_mode: str = "chat",
    clarification_reply: str = "",
    skip_engineering_pipeline: bool = False,
    context_files: list[str] | None = None,
) -> dict:
    from services.llm.llm_gateway import set_model_override, set_reasoning_effort
    set_model_override(model_override)
    if not model_override:
        try:
            import runtime_safety
            _cfg_route = runtime_safety.load_config()
            if _cfg_route.get("tool_routing_enabled", True):
                from services.llm.model_router import classify_task_for_routing, is_routing_enabled
                if is_routing_enabled():
                    set_model_override(classify_task_for_routing(goal, context or "", _cfg_route))
        except Exception as _exc:
            logger.debug("agent_loop:L2536: %s", _exc, exc_info=False)
    # Phase 4.1: record CoT split decision for cost telemetry
    try:
        from services.llm.model_router import _record_cot_phase, split_cot_models
        _cot = split_cot_models()
        if _cot.get("split_enabled"):
            _record_cot_phase("reasoning", _cot.get("reasoning_model"), estimated_tokens=800)
            _record_cot_phase("implementation", _cot.get("implementation_model"), estimated_tokens=1800)
            logger.debug(
                "cot_split: reasoning=%s impl=%s",
                _cot.get("reasoning_model"), _cot.get("implementation_model"),
            )
    except Exception as e:
        logger.debug("agent_loop: %s", e)
    set_reasoning_effort(reasoning_effort)
    # Record the turn's granted permissions so the executor can fail-closed on a destructive tool that
    # reaches it without approval (audit S4 defense-in-depth). Cleared in the finally below.
    try:
        from services.tools.tool_permissions import set_tool_permissions
        set_tool_permissions(allow_write, allow_run)
    except Exception:
        pass
    try:
        return _autonomous_run_impl_core(
            goal, context, workspace_root, allow_write, allow_run,
            conversation_history, aspect_id, show_thinking, stream_final,
            ux_state_queue, research_mode, plan_depth, priority,
            persona_focus,
            conversation_id,
            cognition_workspace_roots,
            client_abort_event,
            background_progress_callback,
            active_plan_id,
            plan_approved,
            fabrication_assist_runner_request=fabrication_assist_runner_request,
            resume_execution_state=resume_execution_state,
            coordinator_trace=coordinator_trace,
            engineering_pipeline_mode=engineering_pipeline_mode,
            clarification_reply=clarification_reply,
            skip_engineering_pipeline=skip_engineering_pipeline,
            context_files=context_files,
        )
    finally:
        set_model_override(None)
        set_reasoning_effort(None)
        try:
            from services.tools.tool_permissions import clear_tool_permissions
            clear_tool_permissions()
        except Exception:
            pass


def _run_tool_guards(
    intent: str,
    decision: dict | None,
    state: dict,
    cfg: dict,
    goal: str,
    workspace: str,
    context: str,
) -> tuple[bool, str]:
    """Run post-batch tool guards (policy, loop, args, dup, recovery)."""
    return _run_tool_guards_impl(
        intent, decision, state, cfg, goal, workspace, context,
        get_tools_for_goal_fn=_get_tools_for_goal,
        log_tool_outcome_fn=_log_tool_outcome,
        format_steps_fn=_format_steps,
        valid_tools=_VALID_TOOLS,
    )


def _finalize_run_state(
    state: dict,
    active_aspect: dict,
    goal: str,
    conversation_history: list | None,
    research_mode: bool,
    emit_run_telemetry_fn: Callable,
) -> None:
    """Post-loop finalization: outcome evaluation, learning extraction, telemetry, response envelope."""
    return _finalize_run_state_impl(
        state, active_aspect, goal, conversation_history, research_mode, emit_run_telemetry_fn,
        inject_cancel_message_fn=_inject_cancel_message,
        auto_extract_learnings_fn=_auto_extract_learnings,
        save_outcome_memory_fn=_save_outcome_memory,
        set_effective_sandbox_fn=set_effective_sandbox,
        runtime_safety_module=runtime_safety,
    )


def _autonomous_run_impl_core(
    goal: str,
    context: str,
    workspace_root: str,
    allow_write: bool,
    allow_run: bool,
    conversation_history: list,
    aspect_id: str,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue: queue.Queue | None,
    research_mode: bool,
    plan_depth: int = 0,
    priority: int = PRIORITY_AGENT,
    persona_focus: str = "",
    conversation_id: str = "",
    cognition_workspace_roots: list[str] | None = None,
    client_abort_event: threading.Event | None = None,
    background_progress_callback: Callable[[dict], None] | None = None,
    active_plan_id: str = "",
    plan_approved: bool = False,
    *,
    fabrication_assist_runner_request: str = "",
    resume_execution_state: dict | None = None,
    coordinator_trace: dict | None = None,
    engineering_pipeline_mode: str = "chat",
    clarification_reply: str = "",
    skip_engineering_pipeline: bool = False,
    context_files: list[str] | None = None,
) -> dict:
    # ------------------------------------------------------------------
    # Phase 1: Setup (services/agent/run_setup.py)
    # ------------------------------------------------------------------
    from services.agent.run_setup import setup_autonomous_run

    setup_result = setup_autonomous_run(
        goal=goal,
        context=context,
        workspace_root=workspace_root,
        allow_write=allow_write,
        allow_run=allow_run,
        conversation_history=conversation_history,
        aspect_id=aspect_id,
        show_thinking=show_thinking,
        stream_final=stream_final,
        ux_state_queue=ux_state_queue,
        research_mode=research_mode,
        plan_depth=plan_depth,
        priority=priority,
        persona_focus=persona_focus,
        conversation_id=conversation_id,
        cognition_workspace_roots=cognition_workspace_roots,
        client_abort_event=client_abort_event,
        background_progress_callback=background_progress_callback,
        active_plan_id=active_plan_id,
        plan_approved=plan_approved,
        fabrication_assist_runner_request=fabrication_assist_runner_request,
        resume_execution_state=resume_execution_state,
        coordinator_trace=coordinator_trace,
        engineering_pipeline_mode=engineering_pipeline_mode,
        clarification_reply=clarification_reply,
        skip_engineering_pipeline=skip_engineering_pipeline,
        context_files=context_files,
    )

    # Early exits: memory command, content guard, system busy, quick reply,
    # engineering pipeline, plan completed.
    if "early_exit" in setup_result:
        return setup_result["early_exit"]

    state = setup_result["state"]
    run_params = setup_result["run_params"]
    active_aspect = run_params["active_aspect"]
    workspace = run_params["workspace"]
    cfg = run_params["cfg"]
    _precomputed_recall = run_params["_precomputed_recall"]
    _emit_run_telemetry = run_params["_emit_run_telemetry"]
    persona_focus_id = run_params["persona_focus_id"]
    temperature = run_params["temperature"]

    # ------------------------------------------------------------------
    # Phase 2: Decision loop (services/agent/decision_loop.py)
    # ------------------------------------------------------------------
    from services.agent.decision_loop import run_decision_loop

    state, goal = run_decision_loop(
        state=state,
        run_params=run_params,
        goal=goal,
        context=context,
        conversation_history=conversation_history,
        show_thinking=show_thinking,
        stream_final=stream_final,
        ux_state_queue=ux_state_queue,
        research_mode=research_mode,
        allow_write=allow_write,
        allow_run=allow_run,
        client_abort_event=client_abort_event,
    )

    # Stream pending early return (from reasoning handler)
    if state.get("status") == "stream_pending":
        _finalize_run_state(
            state=state,
            active_aspect=active_aspect,
            goal=goal,
            conversation_history=conversation_history,
            research_mode=research_mode,
            emit_run_telemetry_fn=_emit_run_telemetry,
        )
        return state

    # ------------------------------------------------------------------
    # Phase 3: Parse-failed fallback
    # ------------------------------------------------------------------
    if state.get("status") == "parse_failed":
        logger.info("parse_failed fallback: generating conversational response for %r", (state.get("original_goal") or "")[:120])
        try:
            _fb_head = _build_system_head(
                goal=state.get("original_goal") or goal,
                aspect=active_aspect,
                workspace_root=workspace,
                sub_goals=state.get("sub_goals"),
                state=state,
                conversation_history=conversation_history or [],
                reasoning_mode=state.get("reasoning_mode", "light"),
                _precomputed_recall=_precomputed_recall,
                persona_focus_id=persona_focus_id,
                cognition_workspace_roots=state.get("cognition_workspace_roots"),
                packed_context=state.get("packed_context") if isinstance(state.get("packed_context"), dict) else None,
            )
            _fb_prompt = orchestrator.build_standard_prompt(
                message=state.get("original_goal") or goal,
                aspect=active_aspect,
                context=context,
                head=_fb_head,
                convo_block="",
            )
            if stream_final:
                state["status"] = "stream_pending"
                state["goal_for_stream"] = state.get("original_goal") or goal
                state["reasoning_mode_for_stream"] = state.get("reasoning_mode", "light")
                state["precomputed_recall_for_stream"] = _precomputed_recall
                state["stream_workspace_root"] = workspace
                state["cognition_workspace_roots_for_stream"] = state.get("cognition_workspace_roots") or []
            else:
                max_tok = cfg.get("completion_max_tokens", 256)
                _fb_out = run_completion(_fb_prompt, max_tokens=max_tok, temperature=temperature, stream=False)
                _fb_text = ""
                if isinstance(_fb_out, str):
                    _fb_text = _fb_out
                elif isinstance(_fb_out, dict):
                    _fb_text = (_fb_out.get("choices") or [{}])[0].get("text") or (_fb_out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                _fb_text = (_fb_text or "").strip()
                _fb_text = truncate_at_next_user_turn(_fb_text)
                _fb_text = _polish_output(_fb_text, cfg)
                if _fb_text and not _is_junk_reply(_fb_text):
                    state["steps"].append({
                        "action": "reason",
                        "result": _fb_text,
                        "deliberated": False,
                        "aspect": active_aspect.get("id"),
                    })
                    state["status"] = "finished"
        except Exception as _fb_exc:
            logger.warning("parse_failed fallback LLM call failed: %s", _fb_exc)

    # ------------------------------------------------------------------
    # Phase 4: Finalization (services/agent/run_finalizer.py)
    # ------------------------------------------------------------------
    _finalize_run_state(
        state=state,
        active_aspect=active_aspect,
        goal=goal,
        conversation_history=conversation_history,
        research_mode=research_mode,
        emit_run_telemetry_fn=_emit_run_telemetry,
    )

    return state
