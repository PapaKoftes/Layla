"""Pre-loop setup: reasoning classification, overload check, aspect selection,
request tracer, quick reply fast-path, memory recall, engineering pipeline,
state creation/initialization, budgets, observer snapshot, cognitive workspace,
planning block, and agent hooks session_start.

Extracted from agent_loop._autonomous_run_impl_core (lines 1421-2032) to reduce
module size.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class _EarlyExit(Exception):
    """Sentinel: the setup phase produced a final result dict (no loop needed)."""

    def __init__(self, result: dict) -> None:
        self.result = result


def setup_autonomous_run(
    goal: str,
    context: str,
    workspace_root: str,
    allow_write: bool,
    allow_run: bool,
    conversation_history: list,
    aspect_id: str,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue,
    research_mode: bool,
    plan_depth: int,
    priority: int,
    persona_focus: str,
    conversation_id: str,
    cognition_workspace_roots: list[str] | None,
    client_abort_event,
    background_progress_callback,
    active_plan_id: str,
    plan_approved: bool,
    *,
    fabrication_assist_runner_request: str = "",
    resume_execution_state: dict | None = None,
    coordinator_trace: dict | None = None,
    engineering_pipeline_mode: str = "chat",
    clarification_reply: str = "",
    skip_engineering_pipeline: bool = False,
    context_files: list[str] | None = None,
) -> dict:
    """Run all pre-loop setup.

    Returns a dict with keys:
        - ``"early_exit"``  (dict) -- a completed result; caller should return it.
        - Otherwise keys: ``"state"``, ``"run_params"``.

    ``run_params`` is a dict with: workspace, max_tool_calls, max_tool_calls_effective,
    max_runtime, temperature, reasoning_mode, active_aspect, cfg, _precomputed_recall,
    _packed_ctx_run, memory_influenced, _dignity_boundary_prompt, _prev_reasoning_mode,
    _emit_run_telemetry, _req_trace, _aspect_miss, _aspect_req, _steps_list, plan_depth.
    """
    # ------------------------------------------------------------------
    # 0. Pre-loop service calls (already extracted to pre_loop_setup)
    # ------------------------------------------------------------------
    from services.pre_loop_setup import (
        build_precomputed_recall,
        check_content_guard,
        check_dignity,
        check_memory_command,
        extract_working_memory,
    )

    _mem_exit = check_memory_command(goal, aspect_id=aspect_id or "")
    if _mem_exit:
        return {"early_exit": _mem_exit}

    extract_working_memory(goal)

    _cg_exit = check_content_guard(goal, aspect_id=aspect_id)
    if _cg_exit:
        return {"early_exit": _cg_exit}

    _dignity_boundary_prompt = check_dignity(goal)

    # ------------------------------------------------------------------
    # 1. Reasoning mode classification + stabilization
    # ------------------------------------------------------------------
    import threading

    import runtime_safety

    persona_focus_id = (persona_focus or "").strip().lower()
    _run_cid = (conversation_id or "").strip() or "default"
    base_cfg = runtime_safety.load_config()

    # We need access to agent_loop module-level state for reasoning mode lock + last mode.
    # Import the module to access its globals.
    import agent_loop as _al

    cfg = _al._get_effective_config(base_cfg)
    _prev_reasoning_mode = ""
    try:
        from services.reasoning_classifier import classify_reasoning_need, stabilize_reasoning_mode

        reasoning_mode = classify_reasoning_need(goal, context or "", research_mode=research_mode)
        if reasoning_mode == "deep" and (cfg.get("performance_mode") or "").strip().lower() in ("low",):
            reasoning_mode = "light"
        with _al._reason_mode_lock:
            _prev_reasoning_mode = _al._last_reasoning_mode
            reasoning_mode = stabilize_reasoning_mode(_prev_reasoning_mode, reasoning_mode)
            _al._last_reasoning_mode = reasoning_mode
    except Exception as e:
        logger.warning("reasoning_classifier failed: %s", e)
        reasoning_mode = "light"
    _run_t0 = time.time()

    # ------------------------------------------------------------------
    # 2. Telemetry helper (closure over _run_t0, _req_trace, research_mode)
    # ------------------------------------------------------------------
    # _req_trace will be set later; we use a mutable container.
    _req_trace_box: list = [None]

    def _emit_run_telemetry(st: dict, success: bool) -> None:
        try:
            _cfg_t = runtime_safety.load_config()
            if not _cfg_t.get("telemetry_enabled", True):
                return
            from services.telemetry import log_event as _tel
            from services.telemetry import log_model_outcome as _log_mo

            _lat_ms = max(0.0, (time.time() - _run_t0) * 1000.0)
            _model_used = str(_cfg_t.get("model_filename") or "")
            _tel(
                task_type="research" if research_mode else "agent",
                reasoning_mode=str(st.get("reasoning_mode") or "light"),
                model_used=_model_used,
                latency_ms=_lat_ms,
                success=success,
                performance_mode=str(_cfg_t.get("performance_mode") or "auto"),
            )
            try:
                oe = st.get("outcome_evaluation") if isinstance(st.get("outcome_evaluation"), dict) else {}
                score = oe.get("score") if isinstance(oe, dict) else None
            except Exception as e:
                logger.debug("outcome_evaluation score extraction failed: %s", e, exc_info=True)
                score = None
            _log_mo(
                model_used=_model_used,
                task_type="research" if research_mode else "agent",
                success=bool(success),
                score=float(score) if score is not None else None,
                latency_ms=_lat_ms,
            )
        except Exception as _exc:
            logger.debug("agent_loop:L2623: %s", _exc, exc_info=False)
        try:
            from services.request_tracer import finish_trace as _rt_finish

            _status_str = "ok" if success else "error"
            _st_status = str((st or {}).get("status") or "")
            if _st_status in ("refused", "system_busy"):
                _status_str = _st_status
            _rt_finish(
                _req_trace_box[0],
                status=_status_str,
                tool_calls=int((st or {}).get("tool_calls") or 0),
            )
        except Exception as e:
            logger.debug("agent_loop: %s", e)

    # ------------------------------------------------------------------
    # 3. System overload check + early return
    # ------------------------------------------------------------------
    from services.resource_manager import PRIORITY_CHAT

    import orchestrator

    def _overloaded_now() -> bool:
        try:
            return _al.system_overloaded(priority=priority)
        except TypeError:
            return _al.system_overloaded()

    if _overloaded_now():
        time.sleep(2.0)
        if _overloaded_now():
            active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
            _aspect_miss = bool(active_aspect.get("_force_aspect_miss")) if isinstance(active_aspect, dict) else False
            _aspect_req = str(active_aspect.get("_force_aspect_requested") or "") if isinstance(active_aspect, dict) else ""
            _emit_run_telemetry({"reasoning_mode": reasoning_mode}, False)
            return {
                "early_exit": {
                    "status": "system_busy",
                    "steps": [],
                    "aspect": active_aspect.get("id", "layla"),
                    "aspect_name": active_aspect.get("name", "Layla"),
                    "aspect_miss_warning": _aspect_req if _aspect_miss else "",
                    "refused": False,
                    "refusal_reason": "",
                    "ux_states": [],
                    "memory_influenced": [],
                    "reasoning_mode": reasoning_mode,
                }
            }

    # ------------------------------------------------------------------
    # 4. Aspect selection
    # ------------------------------------------------------------------
    active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
    _aspect_miss = bool(active_aspect.get("_force_aspect_miss")) if isinstance(active_aspect, dict) else False
    _aspect_req = str(active_aspect.get("_force_aspect_requested") or "") if isinstance(active_aspect, dict) else ""

    try:
        from services.aspect_behavior import apply_reasoning_depth as _ab_apply_depth

        reasoning_mode = _ab_apply_depth(active_aspect, reasoning_mode)
        from services.agent.reasoning_state import get_lock as _rstate_get_lock2, set_ as _rstate_set2
        with _rstate_get_lock2():
            _rstate_set2(reasoning_mode)
    except Exception as _ab_err:
        logger.debug("aspect_behavior depth apply failed: %s", _ab_err)

    # ------------------------------------------------------------------
    # 5. Request tracer
    # ------------------------------------------------------------------
    _req_trace = None
    try:
        from services.request_tracer import start_trace as _rt_start

        _req_trace = _rt_start(
            goal,
            aspect_id=(active_aspect.get("id") or "") if isinstance(active_aspect, dict) else "",
            reasoning_mode=reasoning_mode,
        )
    except Exception as _rt_err:
        logger.debug("request_tracer start failed: %s", _rt_err)
    _req_trace_box[0] = _req_trace

    # ------------------------------------------------------------------
    # 6. Quick reply fast-path
    # ------------------------------------------------------------------
    if reasoning_mode == "none" and not allow_write and not allow_run and not show_thinking:
        from contextvars import ContextVar

        _goal_original_var: ContextVar[str] = ContextVar("layla_goal_original", default="")
        _goal_optimized_var: ContextVar[str] = ContextVar("layla_goal_optimized", default="")
        # Import the actual contextvars from agent_loop
        _goal_original_var = _al._goal_original_var
        _goal_optimized_var = _al._goal_optimized_var

        quick = _al._quick_reply_for_trivial_turn(goal)
        if quick:
            _emit_run_telemetry({"reasoning_mode": reasoning_mode}, True)
            _go_qr = _goal_original_var.get() or goal
            return {
                "early_exit": {
                    "goal": goal,
                    "original_goal": _go_qr,
                    "goal_original": _go_qr,
                    "goal_optimized": _goal_optimized_var.get() or "",
                    "objective": goal,
                    "objective_complete": True,
                    "depth": 0,
                    "steps": [{"action": "reason", "result": quick, "deliberated": False, "aspect": active_aspect.get("id", "layla")}],
                    "status": "finished",
                    "start_time": time.time(),
                    "tool_calls": 0,
                    "aspect": active_aspect.get("id", "layla"),
                    "aspect_name": active_aspect.get("name", "Layla"),
                    "aspect_miss_warning": _aspect_req if _aspect_miss else "",
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
                    "reasoning_mode": reasoning_mode,
                }
            }

    # ------------------------------------------------------------------
    # 7. Memory recall
    # ------------------------------------------------------------------
    _packed_ctx_run, _precomputed_recall, memory_influenced = build_precomputed_recall(
        goal, cfg, workspace_root, reasoning_mode,
        context_files=context_files,
        aspect_id=active_aspect.get("id") or "",
    )

    # ------------------------------------------------------------------
    # 8. Engineering pipeline check
    # ------------------------------------------------------------------
    if (
        not skip_engineering_pipeline
        and bool(cfg.get("engineering_pipeline_enabled"))
        and engineering_pipeline_mode.lower() == "execute"
        and (goal or "").strip()
    ):
        try:
            from services.engineering_pipeline import engineering_planning_locked, run_execute_pipeline

            if not engineering_planning_locked():

                def _agent_run_fn(step_goal: str, **kw: Any) -> dict:
                    kw2 = dict(kw)
                    kw2["engineering_pipeline_mode"] = "chat"
                    kw2["skip_engineering_pipeline"] = True
                    kw2["clarification_reply"] = ""
                    return _al.autonomous_run(step_goal, **kw2)

                return {
                    "early_exit": run_execute_pipeline(
                        goal=goal,
                        context=context or "",
                        workspace_root=workspace_root or "",
                        allow_write=allow_write,
                        allow_run=allow_run,
                        conversation_history=conversation_history or [],
                        aspect_id=aspect_id or "morrigan",
                        show_thinking=show_thinking,
                        stream_final=stream_final,
                        ux_state_queue=ux_state_queue,
                        research_mode=research_mode,
                        plan_depth=plan_depth,
                        persona_focus=persona_focus or "",
                        conversation_id=conversation_id or "",
                        cognition_workspace_roots=cognition_workspace_roots,
                        client_abort_event=client_abort_event,
                        background_progress_callback=background_progress_callback,
                        clarification_reply=clarification_reply or "",
                        cfg=cfg,
                        agent_run_fn=_agent_run_fn,
                        memory_influenced=list(memory_influenced),
                        active_aspect=active_aspect,
                    )
                }
        except Exception as _ep_err:
            logger.warning("engineering pipeline execute failed: %s", _ep_err)

    # ------------------------------------------------------------------
    # 9. Steps list (background progress)
    # ------------------------------------------------------------------
    _prog_on = bool(cfg.get("background_progress_stream_enabled", True))
    _prog_iv = float(cfg.get("background_progress_min_interval_seconds", 0.35) or 0.35)
    if background_progress_callback is not None and _prog_on:
        _steps_list: list = _al._BackgroundProgressSteps(background_progress_callback, interval=_prog_iv)
    else:
        _steps_list = []

    # ------------------------------------------------------------------
    # 10. State creation + initialization
    # ------------------------------------------------------------------
    from execution_state import create_execution_state

    from services.system_head_builder import decompose_goal as _decompose_goal
    from services.system_head_builder import is_lightweight_chat_turn as _is_lightweight_chat_turn

    state = create_execution_state(
        goal=goal,
        sub_goals=_decompose_goal(goal),
        active_aspect=active_aspect,
        memory_influenced=memory_influenced,
        reasoning_mode=reasoning_mode,
        last_reasoning_mode=_prev_reasoning_mode,
        persona_focus_id=persona_focus_id,
        conversation_id=_run_cid,
        active_plan_id=active_plan_id or "",
        plan_approved=plan_approved,
        steps_container=_steps_list,
    )
    if _packed_ctx_run:
        state["packed_context"] = _packed_ctx_run
    if context_files:
        state["context_files"] = [str(x).strip() for x in context_files if str(x).strip()]

    _go = _al._goal_original_var.get() or goal
    _gopt = _al._goal_optimized_var.get()
    state.setdefault("original_goal", _go)
    state["goal_original"] = _go
    state["goal_optimized"] = _gopt or ""
    state["workspace_root"] = (workspace_root or "").strip()
    state["fabrication_assist_runner_request"] = (fabrication_assist_runner_request or "").strip().lower()

    try:
        from services.intent_router import route_intent

        state["route_decision"] = route_intent(goal, context=context or "", workspace_root=workspace_root or "").to_dict()
    except Exception as e:
        logger.debug("agent_loop: %s", e)

    try:
        from services.session_context import get_or_create_session
        _ctr = get_or_create_session(_run_cid).get_coordinator_trace()
        if _ctr:
            state["coordinator_trace"] = _ctr
    except Exception as _cte:
        logger.debug("coordinator_trace attach failed: %s", _cte)

    if coordinator_trace and isinstance(coordinator_trace, dict) and coordinator_trace.get("complexity_score") is not None:
        state["coordinator_trace"] = coordinator_trace

    if resume_execution_state and isinstance(resume_execution_state, dict):
        _rk = (
            "depth", "tool_calls", "consecutive_no_progress", "last_tool_used",
            "strategy_shift_count", "status", "pipeline_stage", "retries",
        )
        for k in _rk:
            if k not in resume_execution_state:
                continue
            v = resume_execution_state[k]
            if v is None:
                continue
            if k == "depth":
                try:
                    state["depth"] = int(v)
                except (TypeError, ValueError):
                    pass
            elif k == "tool_calls":
                try:
                    state["tool_calls"] = int(v)
                except (TypeError, ValueError):
                    state["tool_calls"] = v
            else:
                state[k] = v

    # ------------------------------------------------------------------
    # 11. Workspace + tool/runtime budgets
    # ------------------------------------------------------------------
    workspace = (str(workspace_root).strip() if workspace_root else "") or runtime_safety.load_config().get(
        "sandbox_root", str(Path.home())
    )
    state["cognition_workspace_roots"] = [str(x).strip() for x in (cognition_workspace_roots or []) if str(x).strip()]

    from services.resource_manager import PRIORITY_AGENT as _PA

    RESEARCH_LAB_ROOT = Path(__file__).resolve().parent.parent.parent / ".research_lab"
    if research_mode:
        state["research_lab_root"] = str(RESEARCH_LAB_ROOT)
        max_tool_calls = cfg.get("research_max_tool_calls", 20)
        max_runtime = cfg.get("research_max_runtime_seconds", 1800)
    else:
        max_tool_calls = cfg.get("max_tool_calls", 5)
        max_runtime = cfg.get("max_runtime_seconds", 900)
    max_tool_calls_effective = int(max_tool_calls)

    # Token-pressure cap
    try:
        from services.context_manager import token_estimate_messages as _tem

        _n_ctx_here = max(2048, int(cfg.get("n_ctx", 4096)))
        _hist_ratio = _tem(conversation_history or []) / _n_ctx_here
        if _hist_ratio > 0.6 and not research_mode:
            _capped = min(int(max_tool_calls), 3)
            if _capped < max_tool_calls:
                logger.info(
                    "token_pressure_cap: hist_ratio=%.2f capping max_tool_calls %d->%d",
                    _hist_ratio, max_tool_calls, _capped,
                )
                max_tool_calls = _capped
                max_tool_calls_effective = int(max_tool_calls)
    except Exception as _exc:
        logger.debug("agent_loop:L2810: %s", _exc, exc_info=False)

    # Adaptive task budget
    if cfg.get("task_budget_enabled", True):
        try:
            from services.task_budget import allocate_budget, profile_task

            _tb_prof = profile_task(
                goal, context or "",
                reasoning_mode=reasoning_mode,
                research_mode=research_mode,
                allow_write=allow_write,
                allow_run=allow_run,
            )
            _tb_env = allocate_budget(_tb_prof, cfg)
            max_tool_calls = min(int(max_tool_calls), int(_tb_env.max_tool_calls_effective))
            max_tool_calls_effective = int(max_tool_calls)
            plan_depth = min(int(plan_depth), int(_tb_env.max_plan_depth_effective))
            state["task_budget_profile"] = _tb_prof.to_trace_dict()
            state["task_budget_envelope"] = _tb_env.to_trace_dict()
        except Exception as _tb_e:
            logger.debug("task_budget failed: %s", _tb_e)

    # Light chat cap
    if not allow_write and not allow_run and _is_lightweight_chat_turn(goal, reasoning_mode):
        _light_cap = int(cfg.get("chat_light_max_runtime_seconds", 90) or 90)
        max_runtime = min(int(max_runtime), max(30, _light_cap))
    temperature = cfg.get("temperature", 0.2)

    if research_mode and workspace:
        from layla.tools.registry import set_effective_sandbox

        set_effective_sandbox(workspace)

    # ------------------------------------------------------------------
    # 12. Observer snapshot
    # ------------------------------------------------------------------
    try:
        from core.observer import build_snapshot as _build_snapshot

        state["_snapshot"] = _build_snapshot(
            goal=goal,
            conversation_id=state.get("conversation_id", ""),
            cfg=cfg,
            aspect_id=aspect_id,
            conversation_history=conversation_history,
            workspace_root=workspace,
            allow_write=allow_write,
            allow_run=allow_run,
        )
    except Exception as _obs_err:
        logger.debug("observer.build_snapshot failed (non-fatal): %s", _obs_err)

    # ------------------------------------------------------------------
    # 13. Cognitive workspace deliberation
    # ------------------------------------------------------------------
    try:
        from services.cognitive_workspace import run_deliberation, should_use_cognitive_workspace

        _llm_configured = (
            bool((cfg.get("model_filename") or "").strip())
            or bool(cfg.get("llama_server_url"))
            or bool((cfg.get("ollama_base_url") or "").strip())
        )
        if _llm_configured and should_use_cognitive_workspace(goal, cfg, plan_depth):
            deliberation = run_deliberation(goal, context or "")
            if deliberation.get("strategy_hint"):
                state["cognitive_workspace"] = deliberation
                _al._emit_ux(state, ux_state_queue, _al.UX_STATE_THINKING)
    except Exception as _e:
        logger.debug("cognitive_workspace deliberation failed: %s", _e)

    # ------------------------------------------------------------------
    # 13b. Verification prompt injection (knowledge growth loop)
    # ------------------------------------------------------------------
    try:
        import random as _rng
        from services.verification_queue import get_next_verification
        _pending_v = get_next_verification()
        if _pending_v and _rng.random() < 0.3:  # 30% chance per turn
            _v_count = state.get("_verification_count", 0)
            if _v_count < 3:  # max 3 per session
                state["verification_prompt"] = _pending_v
                state["_verification_count"] = _v_count + 1
    except Exception as _ve:
        logger.debug("verification prompt injection skipped: %s", _ve)

    # ------------------------------------------------------------------
    # 14. Planning block (create_plan + execute_plan with retry ladder)
    # ------------------------------------------------------------------
    try:
        _plan_result = _run_planning_block(
            goal=goal,
            state=state,
            cfg=cfg,
            plan_depth=plan_depth,
            workspace=workspace,
            context=context,
            conversation_history=conversation_history,
            aspect_id=aspect_id,
            active_aspect=active_aspect,
            _aspect_miss=_aspect_miss,
            _aspect_req=_aspect_req,
            show_thinking=show_thinking,
            ux_state_queue=ux_state_queue,
            research_mode=research_mode,
            _run_cid=_run_cid,
            allow_write=allow_write,
            allow_run=allow_run,
            plan_approved=plan_approved,
            reasoning_mode=reasoning_mode,
            memory_influenced=memory_influenced,
            _emit_run_telemetry=_emit_run_telemetry,
        )
        if _plan_result is not None:
            return {"early_exit": _plan_result}
    except Exception as _exc:
        logger.warning("agent_loop:L2950: %s", _exc, exc_info=True)

    # ------------------------------------------------------------------
    # 15. Agent hooks session_start
    # ------------------------------------------------------------------
    try:
        from services.agent_hooks import run_agent_hooks

        run_agent_hooks(
            "session_start",
            allow_run=allow_run,
            conversation_id=str(state.get("conversation_id") or ""),
            workspace_root=workspace,
        )
    except Exception as _exc:
        logger.debug("agent_loop:L2962: %s", _exc, exc_info=False)

    # ------------------------------------------------------------------
    # Return setup results
    # ------------------------------------------------------------------
    return {
        "state": state,
        "run_params": {
            "workspace": workspace,
            "max_tool_calls": int(max_tool_calls),
            "max_tool_calls_effective": int(max_tool_calls_effective),
            "max_runtime": max_runtime,
            "temperature": temperature,
            "reasoning_mode": reasoning_mode,
            "active_aspect": active_aspect,
            "cfg": cfg,
            "_precomputed_recall": _precomputed_recall,
            "_packed_ctx_run": _packed_ctx_run,
            "memory_influenced": memory_influenced,
            "_dignity_boundary_prompt": _dignity_boundary_prompt,
            "_prev_reasoning_mode": _prev_reasoning_mode,
            "_emit_run_telemetry": _emit_run_telemetry,
            "_req_trace": _req_trace,
            "_aspect_miss": _aspect_miss,
            "_aspect_req": _aspect_req,
            "_steps_list": _steps_list,
            "plan_depth": plan_depth,
            "persona_focus_id": persona_focus_id,
            "_run_cid": _run_cid,
        },
    }


# ------------------------------------------------------------------
# Planning sub-routine (internal)
# ------------------------------------------------------------------
def _run_planning_block(
    *,
    goal: str,
    state: dict,
    cfg: dict,
    plan_depth: int,
    workspace: str,
    context: str,
    conversation_history: list,
    aspect_id: str,
    active_aspect: dict,
    _aspect_miss: bool,
    _aspect_req: str,
    show_thinking: bool,
    ux_state_queue,
    research_mode: bool,
    _run_cid: str,
    allow_write: bool,
    allow_run: bool,
    plan_approved: bool,
    reasoning_mode: str,
    memory_influenced: list,
    _emit_run_telemetry,
) -> dict | None:
    """Run the planning block. Returns a result dict if planning completed, else None."""
    from services.system_head_builder import is_lightweight_chat_turn as _is_lightweight_chat_turn

    from services.observability import log_agent_plan_completed, log_agent_plan_created, log_planner_invoked
    from services.planner import (
        create_plan,
        execute_plan_with_optional_graph,
        normalize_plan_steps_tools,
        should_plan,
        validate_plan_before_execution,
    )
    from services.resource_manager import classify_load

    import agent_loop as _al

    _ct_plan = state.get("coordinator_trace") or {}
    try:
        _thr = float(cfg.get("coordinator_plan_threshold", 0.45) or 0.45)
    except (TypeError, ValueError):
        _thr = 0.45
    _cs = _ct_plan.get("complexity_score")
    try:
        _cs_f = float(_cs) if _cs is not None else 0.0
    except (TypeError, ValueError):
        _cs_f = 0.0
    _force_plan = (
        _cs_f >= _thr
        and not _is_lightweight_chat_turn(goal, reasoning_mode)
    )
    _non_trivial = bool(should_plan(goal, cfg, plan_depth=plan_depth, state=state) or _force_plan)
    if not (reasoning_mode != "none" and _non_trivial and bool(cfg.get("planning_enabled", True))):
        return None

    _digest = ""
    if (workspace or "").strip():
        try:
            from services.plan_workspace_store import prior_plans_digest

            _digest = prior_plans_digest(workspace, limit=8)
        except Exception as e:
            logger.debug("prior_plans_digest failed: %s", e, exc_info=True)
            _digest = ""
    _pref_s = None
    try:
        _pref_s = (_ct_plan.get("preferred_strategy") or "").strip() or None
    except Exception as e:
        logger.debug("preferred_strategy extraction failed: %s", e, exc_info=True)
        _pref_s = None
    _attempts = 0
    _last_plan_result: dict[str, Any] | None = None
    try:
        _max_levels = int(cfg.get("structured_retry_max_levels", 3) or 3)
    except (TypeError, ValueError):
        _max_levels = 3
    _max_levels = max(1, min(3, _max_levels))
    _structured_retry = bool(cfg.get("structured_retry_enabled", True))
    max_attempts = _max_levels if _structured_retry else 2
    while _attempts < max_attempts:
        _attempts += 1
        _goal_for_plan = goal
        try:
            from services.aspect_behavior import get_max_steps as _ab_max_steps

            _max_steps = _ab_max_steps(active_aspect, base_limit=None)
        except Exception as e:
            logger.debug("aspect_behavior get_max_steps failed: %s", e, exc_info=True)
            _max_steps = 6
        _model_override = None
        if _attempts == 2 and _last_plan_result is not None:
            _goal_for_plan = (
                (state.get("original_goal") or goal)
                + "\n\n[Retry 1: Previous attempt failed. Fix ONLY the reported failure.]\n"
                + "\n[Last plan execution summary]:\n"
                + str(_last_plan_result.get("summary") or "")[:1200]
            )
        if _attempts >= 3:
            _max_steps = 3
            _goal_for_plan = (
                (state.get("original_goal") or goal)
                + "\n\n[Retry 2/3: Simplify. Use at most 3 steps. Minimal viable solution only.]\n"
                + (
                    "\n[Last plan execution summary]:\n" + str((_last_plan_result or {}).get("summary") or "")[:1200]
                    if _last_plan_result
                    else ""
                )
            )
            if _attempts == 3:
                try:
                    if (cfg.get("coding_model") or "").strip():
                        _model_override = "coding"
                    elif (cfg.get("models") or {}).get("fallback"):
                        _model_override = "fallback"
                except Exception as e:
                    logger.debug("retry model_override selection failed: %s", e, exc_info=True)
                    _model_override = None

        plan = create_plan(
            _goal_for_plan,
            cfg=cfg,
            prior_plans_digest=_digest,
            conversation_id=_run_cid,
            aspect_id=aspect_id or "morrigan",
            preferred_strategy=_pref_s,
            max_steps=_max_steps,
            packed_context=state.get("packed_context") if isinstance(state.get("packed_context"), dict) else None,
        )
        if not plan:
            break
        plan, _plan_ok, _plan_reason = validate_plan_before_execution(
            plan, cfg=cfg, workspace_root=workspace
        )
        if not _plan_ok:
            _last_plan_result = {"summary": f"plan_pre_validation_failed:{_plan_reason}"}
            continue
        if bool(cfg.get("in_loop_plan_governance_enabled")) and bool(
            cfg.get("plan_governance_require_nonempty_step_tools")
        ):
            normalize_plan_steps_tools(plan, cfg)
        _plan_goal_preview = (state.get("original_goal") or goal)[:60]
        log_planner_invoked(steps=len(plan), goal_preview=_plan_goal_preview)
        log_agent_plan_created(steps=len(plan), goal_preview=_plan_goal_preview)
        plan_context = context or ""
        if state.get("cognitive_workspace", {}).get("strategy_hint"):
            plan_context = plan_context + f"\n\n[Chosen approach: {state['cognitive_workspace']['strategy_hint']}]"
        _il_gov = bool(cfg.get("in_loop_plan_governance_enabled"))
        try:
            _dm = int(cfg.get("in_loop_plan_default_max_retries", 1) or 1)
        except (TypeError, ValueError):
            _dm = 1
        _dm = max(0, min(3, _dm))
        _nested_plan_approved = bool(plan_approved) or bool(allow_write) or bool(allow_run)
        _exec_common = dict(
            context=plan_context,
            workspace_root=workspace,
            allow_write=allow_write,
            allow_run=allow_run,
            conversation_history=conversation_history or [],
            aspect_id=aspect_id or "morrigan",
            show_thinking=show_thinking,
            stream_final=False,
            ux_state_queue=ux_state_queue,
            research_mode=research_mode,
            conversation_id=_run_cid,
        )
        if _model_override:
            _exec_common["model_override"] = _model_override
        if _il_gov:
            plan_result = execute_plan_with_optional_graph(
                plan,
                _al.autonomous_run,
                goal_prefix=goal[:100],
                plan_depth=plan_depth,
                step_governance=True,
                default_max_retries=_dm,
                plan_approved=_nested_plan_approved,
                cfg=cfg,
                **_exec_common,
            )
        else:
            plan_result = execute_plan_with_optional_graph(
                plan,
                _al.autonomous_run,
                goal_prefix=goal[:100],
                plan_depth=plan_depth,
                cfg=cfg,
                **_exec_common,
            )
        _last_plan_result = plan_result if isinstance(plan_result, dict) else None
        if (
            _il_gov
            and bool(cfg.get("pipeline_enforcement_enabled", True))
            and isinstance(plan_result, dict)
            and plan_result.get("all_steps_ok") is False
            and _attempts < max_attempts
        ):
            try:
                state["pipeline_stage"] = "DEBUG"
            except Exception as e:
                logger.debug("agent_loop: %s", e)
            goal = state.get("original_goal") or goal
            continue
        log_agent_plan_completed(steps=len(plan_result.get("steps_done", [])))
        _emit_run_telemetry(state, True)
        # Maturity: award XP for successful plan execution
        try:
            from services.maturity_engine import award_xp as _plan_award_xp
            _plan_id = plan_result.get("plan_id", "")
            _plan_award_xp(20, reason=f"plan_executed:{_plan_id}"[:80])
        except Exception:
            pass
        _pc_out: dict = {
            "status": "plan_completed",
            "steps": plan_result.get("steps_done", []),
            "aspect": active_aspect.get("id", "layla"),
            "aspect_name": active_aspect.get("name", "Layla"),
            "aspect_miss_warning": _aspect_req if _aspect_miss else "",
            "refused": False,
            "refusal_reason": "",
            "ux_states": state.get("ux_states", []),
            "memory_influenced": memory_influenced,
            "reply": plan_result.get("summary", ""),
            "reasoning_mode": reasoning_mode,
            "load": classify_load(),
        }
        if _il_gov and isinstance(plan_result, dict) and "all_steps_ok" in plan_result:
            _pc_out["all_steps_ok"] = bool(plan_result.get("all_steps_ok"))
        return _pc_out
    # If we broke out without returning, allow the loop path to handle response.
    return None
