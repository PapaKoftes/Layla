"""Main agent decision loop: iterate decision->intent->tool/reason until
done, timeout, or tool limit.

Extracted from agent_loop._autonomous_run_impl_core (lines 2033-2729) to
reduce module size.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def run_decision_loop(
    state: dict,
    run_params: dict,
    goal: str,
    context: str,
    conversation_history: list,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue,
    research_mode: bool,
    allow_write: bool,
    allow_run: bool,
    client_abort_event,
) -> tuple[dict, str]:
    """Execute the main agent decision loop.

    Modifies *state* in-place.

    Returns ``(state, goal)`` -- the possibly-updated goal string is needed
    by the post-loop parse_failed fallback.
    """
    import agent_loop as _al
    import runtime_safety
    from layla.tools.registry import TOOLS
    from services.agent.reasoning_handler import handle_reasoning_intent
    from services.infrastructure.resource_manager import classify_load
    from services.safety.agent_safety import (
        maybe_planning_strict_refusal as _maybe_planning_strict_refusal,
    )
    from services.safety.agent_safety import (
        maybe_step_tool_allowlist_refusal as _maybe_step_tool_allowlist_refusal,
    )

    cfg = run_params["cfg"]
    active_aspect = run_params["active_aspect"]
    workspace = run_params["workspace"]
    max_tool_calls = run_params["max_tool_calls"]
    max_tool_calls_effective = run_params["max_tool_calls_effective"]
    max_runtime = run_params["max_runtime"]
    run_params["temperature"]
    reasoning_mode = run_params["reasoning_mode"]
    _precomputed_recall = run_params["_precomputed_recall"]
    _dignity_boundary_prompt = run_params["_dignity_boundary_prompt"]
    _aspect_miss = run_params["_aspect_miss"]
    _aspect_req = run_params["_aspect_req"]
    persona_focus_id = run_params["persona_focus_id"]

    _VALID_TOOLS = _al._VALID_TOOLS

    while state["depth"] < 5:
        state["tool_attempted_this_turn"] = False

        # -- Decision policy caps --
        try:
            if cfg.get("decision_policy_enabled", True):
                from services.safety.decision_policy import build_policy_caps as _build_policy_caps
                from services.safety.decision_policy import effective_max_tool_calls as _effective_max_tool_calls

                _cid = (state.get("conversation_id") or "").strip() or "unknown"
                _caps = _build_policy_caps(state, cfg, conversation_id=_cid)
                state["policy_caps"] = _caps.to_trace_dict()
                max_tool_calls_effective = _effective_max_tool_calls(int(max_tool_calls), _caps)
        except Exception as e:
            logger.warning("decision_policy caps in loop failed: %s", e)
            max_tool_calls_effective = int(max_tool_calls)

        # -- Client abort check --
        if client_abort_event is not None and client_abort_event.is_set():
            state["status"] = "client_abort"
            _last_tool = (state.get("last_tool_used") or "agent") if isinstance(state.get("last_tool_used"), str) else "agent"
            state["steps"].append({
                "action": "client_abort",
                "result": {
                    "ok": False,
                    "reason": "client_abort",
                    "message": "Client disconnected or cancelled the request.",
                },
            })
            if conversation_history is not None:
                _al._inject_cancel_message(conversation_history, _last_tool, "interrupted (client disconnect)")
            state["response"] = "Request cancelled (client disconnected)."
            break

        # -- Timeout / tool limit --
        if time.time() - state["start_time"] > max_runtime:
            state["status"] = "timeout"
            break

        if state["tool_calls"] >= max_tool_calls_effective:
            state["status"] = "tool_limit"
            # Exhausting the tool budget must still END WITH AN ANSWER. Previously this broke
            # straight out and the router surfaced the internal status as the reply ("Stopped
            # after maximum tool calls…") — even when the gathered tool results were plenty to
            # answer from. Force ONE wrap-up reasoning pass that synthesizes from the work above;
            # in the streaming case this hands off via stream_pending so the answer streams.
            if not (state.get("response") or "").strip():
                try:
                    _wrap_goal = (
                        goal
                        + "\n\n(Tool budget exhausted — do NOT use more tools. Answer the user "
                        "directly now from what you already gathered above; if something is "
                        "missing, say what briefly.)"
                    )
                    _g2, _wrap_flow = handle_reasoning_intent(
                        state=state,
                        run_params=run_params,
                        goal=_wrap_goal,
                        context=context,
                        conversation_history=conversation_history,
                        show_thinking=show_thinking,
                        stream_final=stream_final,
                        ux_state_queue=ux_state_queue,
                        persona_focus_id=persona_focus_id,
                    )
                    if _wrap_flow == "return":
                        return state, _g2
                except Exception as _wrap_exc:
                    logger.debug("tool_limit wrap-up reasoning failed: %s", _wrap_exc)
            break

        # -- Strategy shift hint --
        if state.get("consecutive_no_progress", 0) >= 2 and not state.get("objective_complete"):
            state["strategy_shift_count"] = state.get("strategy_shift_count", 0) + 1
            _al._emit_ux(state, ux_state_queue, _al.UX_STATE_CHANGING_APPROACH)

        _al._emit_context_window_ux(ux_state_queue, conversation_history, cfg, state)
        _al._emit_ux(state, ux_state_queue, _al.UX_STATE_THINKING)

        # -- Steer hint injection --
        goal_for_decision = goal
        try:
            from services.infrastructure.session_context import get_or_create_session
            steer = get_or_create_session(state.get("conversation_id") or "default").pop_steer_hint()
            if steer:
                goal_for_decision = (
                    goal
                    + "\n\n[Operator steer -- brief redirect; honor if compatible with the same task]\n"
                    + steer
                )
        except Exception as _exc:
            logger.debug("agent_loop:L3007: %s", _exc, exc_info=False)

        # -- Packed context injection --
        try:
            if cfg.get("inject_packed_context_in_decisions", True) and state.get("packed_context"):
                from services.context.context_builder import format_tool_context

                _gh = format_tool_context(
                    state["packed_context"],
                    max_chars=int(cfg.get("tool_loop_packed_context_chars", 1200) or 1200),
                )
                if _gh:
                    goal_for_decision = goal_for_decision + "\n\n[Retrieval context]\n" + _gh
        except Exception as _gfc:
            logger.debug("packed_context decision hint: %s", _gfc)

        # -- Context protection / compression --
        try:
            from services.context.context_manager import summarize_history, token_estimate_messages

            n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
            thr = float(cfg.get("context_protection_threshold", 0.60) or 0.60)
            thr = max(0.35, min(0.85, thr))
            ch = conversation_history or []
            if ch and token_estimate_messages(ch) > int(n_ctx * thr):
                conversation_history = summarize_history(
                    list(ch),
                    n_ctx=n_ctx,
                    threshold_ratio=thr,
                    keep_recent_messages=max(6, int(cfg.get("context_sliding_keep_messages", 0) or 0)),
                )
        except Exception as _exc:
            logger.debug("context protection skipped: %s", _exc, exc_info=False)

        # -- Step summarization --
        try:
            step_thr = int(cfg.get("step_summarization_threshold", 8) or 8)
        except (TypeError, ValueError):
            step_thr = 8
        if isinstance(state.get("steps"), list) and len(state["steps"]) > max(6, step_thr):
            state["steps_summary"] = _al._summarize_steps_deterministic(state["steps"], keep_last=5, max_lines=12)

        # -- FAST PATH: a self-contained question on the first step (read-only chat) is forced
        #    to `reason` below anyway, so skip the decision LLM call entirely — otherwise a
        #    trivial question pays TWO sequential model calls (decision + answer, ~25s each on
        #    CPU) when the decision was a foregone conclusion. Same outcome, half the latency. --
        _force_reason_now = False
        try:
            _force_reason_now = bool(
                int(state.get("tool_calls", 0) or 0) == 0
                and not allow_write and not allow_run
                and not state.get("_forced_reason_first")
                and _al._is_self_contained_question(state.get("original_goal") or goal or "")
            )
        except Exception:
            _force_reason_now = False

        # -- LLM decision call (skipped on the fast path above) --
        _t0 = time.perf_counter()
        decision = None if _force_reason_now else _al._llm_decision(
            goal_for_decision, state, context, active_aspect, show_thinking, conversation_history or []
        )
        if decision and isinstance(decision, dict):
            state["last_decision"] = dict(decision)
        try:
            from services.observability import log_agent_decision

            log_agent_decision(duration_ms=(time.perf_counter() - _t0) * 1000)
        except Exception as _exc:
            logger.debug("agent_loop:L3016: %s", _exc, exc_info=False)

        # -- Intent routing --
        if decision:
            state["objective_complete"] = bool(decision.get("objective_complete", False))
            state["priority_level"] = decision.get("priority_level") or "medium"
            state["impact_estimate"] = decision.get("impact_estimate")
            state["effort_estimate"] = decision.get("effort_estimate")
            state["risk_estimate"] = decision.get("risk_estimate")

            if decision.get("action") == "think":
                thought = (decision.get("thought") or "").strip()
                state["_think_seq"] = int(state.get("_think_seq") or 0) + 1
                _tn = int(state["_think_seq"])
                if thought:
                    state["steps"].append({
                        "action": "think",
                        "result": {"ok": True, "thought": thought[:4000]},
                    })
                if show_thinking and ux_state_queue is not None:
                    try:
                        ux_state_queue.put({
                            "_type": "think",
                            "content": thought[:2000] if thought else "",
                            "step": _tn,
                        })
                    except Exception as _exc:
                        logger.debug("agent_loop:L3042: %s", _exc, exc_info=False)
                goal = (
                    state["original_goal"]
                    + "\n\n[Internal reasoning]\n"
                    + (thought or "(no thought text)")
                    + "\n\n[Tool results so far]:\n"
                    + _al._format_steps(state["steps"])
                )
                continue

            if decision.get("action") == "reason" or state["objective_complete"]:
                intent = "reason"
            elif decision.get("action") == "none":
                intent = "none"
            elif decision.get("action") == "tool" and decision.get("tool") and decision["tool"] in _VALID_TOOLS:
                intent = decision["tool"]
            elif decision.get("action") == "tool":
                try:
                    chosen = str(decision.get("tool") or "").strip()
                    if chosen and chosen not in _VALID_TOOLS:
                        _gap_goal = (state.get("original_goal") or goal or "")[:120]
                        logger.info("skill_gap: goal=%s tool=%s err=%s", _gap_goal, chosen, "unknown_tool")
                except Exception as e:
                    logger.debug("agent_loop: %s", e)
                intent = "reason"
            else:
                intent = _al.classify_intent((state.get("original_goal") or goal or "").strip())
        else:
            intent = _al.classify_intent((state.get("original_goal") or goal or "").strip())

        # -- Reason-first for self-contained questions (golden-eval fix) --
        # In chat mode, a general-knowledge / math / writing / reasoning question the model
        # can answer on its own should NOT burn tool calls (and risk max-tool-calls / raw
        # dict leaks). On the first substantive step, force `reason` so it answers directly.
        try:
            if (
                intent not in ("reason", "none", "finish", "wakeup")
                and int(state.get("tool_calls", 0) or 0) == 0
                and not allow_write and not allow_run
                and not state.get("_forced_reason_first")
                and _al._is_self_contained_question(state.get("original_goal") or goal or "")
            ):
                state["_forced_reason_first"] = True
                intent = "reason"
        except Exception as _rf_exc:
            logger.debug("reason-first fast path skipped: %s", _rf_exc)

        # When we skipped the decision call above, force `reason` so the self-contained
        # question is answered directly (equivalent to what the reason-first path would do).
        if _force_reason_now:
            state["_forced_reason_first"] = True
            intent = "reason"

        # -- Revised objective --
        consecutive = state.get("consecutive_no_progress", 0)
        objective_complete = state.get("objective_complete", False)
        revised_objective = decision.get("revised_objective") if decision else None
        if revised_objective and isinstance(revised_objective, str) and revised_objective.strip():
            _al._emit_ux(state, ux_state_queue, _al.UX_STATE_REFRAMING_OBJECTIVE)
            state["reflection_pending"] = True
            state["objective"] = revised_objective.strip()
            state.setdefault("original_goal", revised_objective.strip())
            state["consecutive_no_progress"] = 0
            state["strategy_shift_count"] = 0
            goal = state["objective"]
            continue
        if consecutive >= 2 and not objective_complete and state.get("strategy_shift_count", 0) >= 2:
            _al._emit_ux(state, ux_state_queue, _al.UX_STATE_CHANGING_APPROACH)
            state["reflection_pending"] = True
            intent = "reason"

        # -- Intent == none --
        if intent == "none":
            state["steps"].append({
                "action": "none",
                "result": {"ok": True, "message": "No action needed"},
            })
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _al._format_steps(state["steps"])
            continue

        # -- Planning strict refusal --
        _ps = _maybe_planning_strict_refusal(intent, cfg, state, allow_write, allow_run)
        if _ps:
            state["tool_calls"] += 1
            state["steps"].append({"action": intent, "result": _ps})
            _al._log_tool_outcome(intent, _ps)
            state["last_tool_used"] = intent
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _al._format_steps(state["steps"])
            continue

        # -- Allowlist refusal --
        if intent not in ("reason", "finish", "wakeup", "none") and intent in _VALID_TOOLS:
            _alr = _maybe_step_tool_allowlist_refusal(intent, cfg)
            if _alr:
                state["tool_calls"] += 1
                state["steps"].append({"action": intent, "result": _alr})
                _al._log_tool_outcome(intent, _alr)
                state["last_tool_used"] = intent
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _al._format_steps(state["steps"])
                continue

        # -- Tool preflight --
        if intent not in ("reason", "finish", "wakeup", "none") and intent in _VALID_TOOLS:
            try:
                from services.tools.tool_preflight import preflight_tool

                pf = preflight_tool(intent=intent, decision=decision, goal=state.get("original_goal") or goal, workspace_root=workspace or "")
                state["preflight_ok"] = bool(pf.ok)
                state["preflight_reason"] = pf.reason if not pf.ok else ""
                if not pf.ok:
                    state.setdefault("steps", []).append({
                        "action": "preflight",
                        "result": {
                            "ok": False,
                            "reason": "missing_required_args",
                            "message": pf.reason,
                            "suggested_action": pf.suggested_action,
                            "missing": pf.missing or [],
                            "tool": intent,
                        },
                    })
                    intent = "reason"
            except Exception as _pf_exc:
                logger.warning("tool_preflight skipped: %s", _pf_exc, exc_info=True)

        # -- Concurrent batch tool execution --
        _extra_batch = [
            bt for bt in (decision.get("batch_tools") or [])
            if isinstance(bt, dict)
            and bt.get("tool") in _VALID_TOOLS
            and TOOLS.get(bt["tool"], {}).get("concurrency_safe")
            and bt["tool"] != intent
        ] if (
            intent not in ("reason", "finish", "wakeup", "none")
            and intent in _VALID_TOOLS
            and TOOLS.get(intent, {}).get("concurrency_safe")
            and not state.get("research_lab_root")
        ) else []

        if _extra_batch and state["tool_calls"] + 1 + len(_extra_batch) <= max_tool_calls_effective:
            _batch_blocked = _run_concurrent_batch(
                state=state,
                intent=intent,
                decision=decision,
                _extra_batch=_extra_batch,
                cfg=cfg,
                workspace=workspace,
                allow_run=allow_run,
                allow_write=allow_write,
                ux_state_queue=ux_state_queue,
                _VALID_TOOLS=_VALID_TOOLS,
            )
            if _batch_blocked == "continue":
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _al._format_steps(state["steps"])
                continue
            if _batch_blocked == "done":
                _al._run_verification_after_tool(
                    state,
                    state.get("_batch_last_tool", intent),
                    (state["steps"][-1].get("result") if state.get("steps") else {}) if isinstance(state.get("steps"), list) else {},
                    workspace,
                )
                _al._emit_ux(state, ux_state_queue, _al.UX_STATE_VERIFYING)
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _al._format_steps(state["steps"])
                logger.info("concurrent batch: ran %d tools in parallel", 1 + len(_extra_batch))
                continue

        # -- Emit tool_start --
        if intent not in ("reason", "finish", "wakeup"):
            _al._emit_tool_start(ux_state_queue, intent)

        # -- Tool guards --
        _guard_blocked, goal = _al._run_tool_guards(
            intent=intent,
            decision=decision,
            state=state,
            cfg=cfg,
            goal=goal,
            workspace=workspace,
            context=context or "",
        )
        if _guard_blocked:
            continue

        # -- Tool dispatch --
        from services.tools.tool_dispatch import DispatchContext, dispatch_tool_intent

        _dispatch_ctx = DispatchContext(
            state=state,
            cfg=cfg,
            workspace=workspace,
            decision=decision,
            allow_write=allow_write,
            allow_run=allow_run,
            reasoning_mode=reasoning_mode,
            ux_state_queue=ux_state_queue,
            show_thinking=show_thinking,
        )
        _dispatch_result = dispatch_tool_intent(intent, goal, _dispatch_ctx)
        if _dispatch_result.handled:
            goal = _dispatch_result.goal
            if _dispatch_result.flow == "break":
                break
            continue

        # -- Reasoning intent --
        if intent == "reason":
            goal, flow = handle_reasoning_intent(
                state=state,
                run_params=run_params,
                goal=goal,
                context=context,
                conversation_history=conversation_history,
                show_thinking=show_thinking,
                stream_final=stream_final,
                ux_state_queue=ux_state_queue,
                persona_focus_id=persona_focus_id,
            )
            if flow == "return":
                return state, goal
            if flow == "break":
                break
            # flow == "continue"
            continue

        # -- D5: Post-step approval/timeout injection --
        _last_step = state["steps"][-1] if state.get("steps") else None
        if _last_step:
            _last_res = _last_step.get("result", {})
            _last_reason = _last_res.get("reason") if isinstance(_last_res, dict) else ""
            _last_tool_name = _last_step.get("action", "tool")
            if _last_reason == "approval_required" and conversation_history is not None:
                _al._inject_cancel_message(conversation_history, _last_tool_name, "pending operator approval")
            elif isinstance(_last_res, dict) and _last_res.get("timed_out") and conversation_history is not None:
                _al._inject_cancel_message(conversation_history, _last_tool_name, "timed out")

        state["depth"] += 1

        # -- Resource-aware chunking --
        if state["tool_calls"] > 0 and state["tool_calls"] % 2 == 0:
            try:
                _load = classify_load()
                _load_level = _load.get("level", "ok")
                if _load_level in ("high", "critical"):
                    _consecutive_high = state.get("_consecutive_high_load", 0) + 1
                    state["_consecutive_high_load"] = _consecutive_high
                    sleep_s = 5.0 if _load_level == "critical" else 2.0
                    logger.info(
                        "resource_chunking: load=%s consecutive=%d sleeping=%.0fs",
                        _load_level, _consecutive_high, sleep_s,
                    )
                    time.sleep(sleep_s)
                    if _load_level == "critical" and _consecutive_high >= 2:
                        state["checkpoint"] = {
                            "steps": list(state.get("steps", [])),
                            "goal": goal,
                            "original_goal": state.get("original_goal", goal),
                            "tool_calls": state["tool_calls"],
                            "depth": state["depth"],
                        }
                        state["status"] = "paused_high_load"
                        break
                else:
                    state["_consecutive_high_load"] = 0
            except Exception as _re:
                logger.debug("resource_chunking check failed: %s", _re)

    return state, goal


# ------------------------------------------------------------------
# Concurrent batch helper (internal)
# ------------------------------------------------------------------
def _run_concurrent_batch(
    *,
    state: dict,
    intent: str,
    decision: dict | None,
    _extra_batch: list,
    cfg: dict,
    workspace: str,
    allow_run: bool,
    allow_write: bool,
    ux_state_queue,
    _VALID_TOOLS,
) -> str:
    """Run concurrent batch tools. Returns 'continue' (blocked), 'done' (ran), or '' (skip)."""
    import agent_loop as _al
    import runtime_safety
    from core.executor import run_tool as _run_tool
    from layla.tools.registry import TOOLS
    from services.safety.agent_safety import (
        maybe_planning_strict_refusal as _maybe_planning_strict_refusal,
    )
    from services.safety.agent_safety import (
        maybe_step_tool_allowlist_refusal as _maybe_step_tool_allowlist_refusal,
    )

    _batch_tools_check = [intent] + [str(bt.get("tool") or "") for bt in _extra_batch]
    _blocked_bt = None
    for _tcheck in _batch_tools_check:
        if not _tcheck:
            continue
        _pbx = _maybe_planning_strict_refusal(_tcheck, cfg, state, allow_write, allow_run)
        if _pbx:
            _blocked_bt = (_tcheck, _pbx)
            break
        _alx = _maybe_step_tool_allowlist_refusal(_tcheck, cfg)
        if _alx:
            _blocked_bt = (_tcheck, _alx)
            break
    if _blocked_bt:
        _tcheck, _pbx = _blocked_bt
        state["tool_calls"] += 1
        state["steps"].append({"action": _tcheck, "result": _pbx})
        _al._log_tool_outcome(_tcheck, _pbx)
        state["last_tool_used"] = _tcheck
        return "continue"

    import concurrent.futures as _cf
    import functools as _fn

    from services.infrastructure.worker_pool import tool_batch_max_workers

    _tool_timeout = float(cfg.get("tool_call_timeout_seconds", 60))
    _primary_args = _al._inject_workspace_args(intent, (decision.get("args") or {}) if decision else {}, workspace)
    _batch: list[tuple[str, dict]] = [(intent, _primary_args)] + [
        (bt["tool"], _al._inject_workspace_args(bt["tool"], bt.get("args") or {}, workspace))
        for bt in _extra_batch
    ]
    _batch_results: list[dict | None] = [None] * len(_batch)
    _hook_cid = str(state.get("conversation_id") or "")
    _pool_workers = tool_batch_max_workers(cfg, len(_batch))
    with _cf.ThreadPoolExecutor(max_workers=_pool_workers, thread_name_prefix="layla_cbatch") as _pool:
        _futs = {
            _pool.submit(
                _fn.partial(
                    _run_tool,
                    _bt,
                    _ba,
                    timeout_s=_tool_timeout,
                    sandbox_root=workspace,
                    allow_run=allow_run,
                    conversation_id=_hook_cid,
                )
            ): _idx
            for _idx, (_bt, _ba) in enumerate(_batch)
        }
        for _fut in _cf.as_completed(_futs):
            _bidx = _futs[_fut]
            try:
                _batch_results[_bidx] = _fut.result()
            except Exception as _be:
                _batch_results[_bidx] = {"ok": False, "error": str(_be)}
    for _bidx, (_bt, _ba) in enumerate(_batch):
        _br = _batch_results[_bidx] if _batch_results[_bidx] is not None else {"ok": False, "error": "batch slot empty"}
        runtime_safety.log_execution(_bt, _ba)
        state["tool_calls"] += 1
        _al._register_exact_tool_call(state, _bt, decision if _bidx == 0 else None)
        _res = _al._maybe_validate_tool_output(_bt, _br)
        _res, _ok_det, _det_reason = _al._apply_deterministic_tool_verification(
            _bt, _res, workspace=workspace, cfg=cfg
        )
        if not _ok_det and isinstance(_res, dict):
            _res["_deterministic_retry_skipped"] = True
            _res["_deterministic_retry_reason"] = _det_reason
        state["steps"].append({"action": _bt, "result": _res})
        state["last_tool_used"] = _bt
        _al._emit_tool_start(ux_state_queue, _bt)
    state["_batch_last_tool"] = _batch[-1][0]
    return "done"
