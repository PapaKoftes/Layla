"""Post-loop finalization: outcome evaluation, learning extraction,
personality evolution, maturity tracking, telemetry, response envelope.

Extracted from agent_loop._finalize_run_state to reduce module size.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def finalize_run_state(
    state: dict,
    active_aspect: dict,
    goal: str,
    conversation_history: list | None,
    research_mode: bool,
    emit_run_telemetry_fn: Callable,
    *,
    inject_cancel_message_fn: Callable,
    save_outcome_memory_fn: Callable[[dict], None],
    set_effective_sandbox_fn: Callable,
    runtime_safety_module: Any,
) -> None:
    """Post-loop finalization: outcome evaluation, learning extraction, telemetry, response envelope."""
    # D5: runtime timeout also warrants a cancel message
    if state.get("status") == "timeout" and conversation_history is not None:
        inject_cancel_message_fn(conversation_history, "agent", "hit runtime limit")

    if state.get("status") == "finished":
        try:
            if runtime_safety_module.load_config().get("pipeline_enforcement_enabled", True):
                state["pipeline_stage"] = "REFLECT"
        except Exception as e:
            logger.warning("pipeline_enforcement config check failed: %s", e, exc_info=True)
            state["pipeline_stage"] = "REFLECT"
        try:
            from services.infrastructure.outcome_evaluation import evaluate_outcome_structured
            from services.infrastructure.session_context import get_or_create_session

            ev_struct = evaluate_outcome_structured(state)
            state["outcome_evaluation"] = ev_struct
            cid_fin = (state.get("conversation_id") or "").strip()
            if cid_fin:
                get_or_create_session(cid_fin).set_outcome_evaluation(ev_struct)
            # Mandatory outcome recording for feedback loop: persist strategy patterns
            try:
                from layla.memory import strategy_stats as _strategy_stats

                _g = (state.get("original_goal") or state.get("goal") or "").strip()
                _task_type = (_g.replace("\n", " ")[:120] if _g else "general") or "general"
                _strat = str(active_aspect.get("id") or "morrigan")[:120]
                _strategy_stats.record_strategy_stat(_task_type, _strat, success=bool(ev_struct.get("success")))
                state["strategy_stats_recorded"] = True
            except Exception as _ss_exc:
                logger.warning("strategy_stats record failed (outcome feedback at risk): %s", _ss_exc)
        except Exception as _ev_exc:
            logger.warning("outcome evaluation failed (feedback loop at risk): %s", _ev_exc)
        save_outcome_memory_fn(state)
        # BL-190 mood nudge MOVED to services/agent/turn_commit.commit_turn. It reads only the
        # user's message + a success boolean, and this gate never fires on a streamed turn
        # (status=="stream_pending"), which is why mood stayed permanently neutral for the ~17/24
        # of real turns that stream. It now runs on the turn boundary for every path. Do NOT
        # restore it here: an orchestrated streamed turn calls BOTH this finalizer and
        # commit_turn, so a copy here would double-nudge.
        #
        # BL-338: the synchronous `run_distill_after_outcome(n=50)` that used to sit here is
        # DELETED, not debounced. A scheduler already owns distillation —
        # layla/scheduler/registry.py registers `_bg_memory` (-> memory_consolidation
        # .consolidate_periodic -> run_distill_after_outcome(n=30)) on an IntervalTrigger of
        # `background_memory_consolidation_interval_minutes` (default 30, floor 5). Running it
        # again per-turn was redundant with a correctly-placed periodic job, and its real cost is
        # not the O(n^2) Jaccard grouping but `_merge_groups`' embed() forward pass + vector/DB
        # writes on a CPU-only box. Wiring learning to EVERY turn (as BL-338 does) would have
        # turned that redundancy into a per-turn tax. The knob to raise freshness already exists.
        # Skill acquisition (BL-238): a finished multi-step run is a reusable procedure. Turn its
        # successful tool sequence into a named learned skill so `learned_skills` actually fills
        # from what Layla DID (previously acquire_from_run had no caller and the store stayed empty).
        # Selective (≥3 tool steps) so ordinary chat/Q&A turns never mint a skill; non-blocking.
        try:
            if runtime_safety_module.load_config().get("skill_acquisition_enabled", True):
                import threading as _t

                def _acquire_skill() -> None:
                    try:
                        from services.skills.skill_acquisition import acquire_from_run
                        acquire_from_run(state, min_steps=3)
                    except Exception as _sk_exc:
                        logger.debug("skill acquisition failed: %s", _sk_exc)

                _t.Thread(target=_acquire_skill, daemon=True, name="skill-acquire").start()
        except Exception as _sk_gate_exc:
            logger.debug("skill acquisition gate failed: %s", _sk_gate_exc)
        final_text = ""
        for s in reversed(state.get("steps", [])):
            if s.get("action") == "reason":
                r = s.get("result", "")
                final_text = r if isinstance(r, str) else ""
                break
        # BL-338/BL-376: learning extraction MOVED to services/agent/turn_commit.commit_turn.
        #
        # Two reasons it could never live here. (1) Liveness: this whole block sits under
        # `status == "finished"`, but reasoning_handler returns with status="stream_pending"
        # BEFORE the answer exists whenever stream_final=True — and the UI ships streaming ON by
        # default. So the learning pipeline only ever ran when the operator manually unchecked
        # "Stream responses". (2) Reach: the router's fast paths never call agent_loop at all, so
        # there is no state here to gate on for ~17/24 real turns. Learning belongs on the TURN
        # BOUNDARY, which is commit_turn, not on the run's completion status.
        #
        # The `clean_reply_text` sanitation that used to guard this call is also gone, and its
        # absence is not a regression: post-BL-376 the extractor does not read the assistant's
        # reply at all (it reads the OPERATOR's turn), so system-prompt bleed in `final_text` can
        # no longer reach the learnings table by this route. The structural floor
        # (is_memory_junk / _LEARNING_REJECT_RE) still guards every writer at the choke point.
        #
        # Do NOT restore an extraction call here: an orchestrated stream=false turn calls BOTH
        # this finalizer and commit_turn, so a copy would extract the same exchange twice.
        # A1 (BL-100/BL-102): run the groundedness + escalation assessment on the final answer
        # and attach it as `answer_quality` when the feature is enabled. `assess_answer` is a
        # cheap no-op while both flags are off, so this is inert by default and never mutates the
        # answer — the UI/caller can surface citations, confidence, and abstain/escalate signals.
        if final_text and not state.get("refused"):
            try:
                from services.llm.answer_assessment import assess_answer

                _aq_cfg = runtime_safety_module.load_config()
                _q = assess_answer(
                    final_text,
                    state.get("original_goal") or goal or "",
                    _aq_cfg,
                    current_model=str(_aq_cfg.get("model_filename") or ""),
                )
                if _q and (_q.get("grounding", {}).get("enabled") or _q.get("escalate")):
                    state["answer_quality"] = _q
            except Exception as _aq_exc:
                logger.debug("answer_quality assessment failed: %s", _aq_exc)
        # BL-237: attach a concise, human-readable "why" (distinct from raw CoT) when the
        # explainable-reasoning flag is on. Deterministic — reuses the trace, no extra model call.
        try:
            if runtime_safety_module.load_config().get("explainable_reasoning_enabled"):
                from services.agent.explain import explain_state
                state["explanation"] = explain_state(state, answer=final_text)
        except Exception as _ex_exc:
            logger.debug("explanation build failed: %s", _ex_exc)
    # BL-338: conversation entity extraction MOVED to services/agent/turn_commit.commit_turn.
    # It was NOT status-gated, so it looked live — but it read the `reason` step's text, which is
    # empty on a stream_pending run because the answer had not been generated yet. It was dead by
    # STARVATION, not by gate: fixing the status gate alone would never have revived it. commit_turn
    # is handed the finished, cleaned reply, so it has text to work with on every path.
    if research_mode:
        set_effective_sandbox_fn(None)

    # Personality evolution: record interaction and update relationship tracking
    try:
        from services.personality.evolution import get_personality_evolution, infer_interaction_type

        _evo = get_personality_evolution()
        _evo_aspect_id = active_aspect.get("id", "") if isinstance(active_aspect, dict) else ""
        if _evo_aspect_id:
            _evo_tools = list(state.get("tools_used", []))
            _evo_itype = infer_interaction_type(_evo_tools)
            _evo.record_interaction(
                _evo_aspect_id,
                _evo_itype,
                {"tools_used": _evo_tools},
            )
    except Exception as _evo_exc:
        logger.debug("personality_evolution record_interaction failed: %s", _evo_exc)

    # Maturity: record daily activity for relationship tracking
    try:
        from services.personality.maturity_engine import record_relationship_event
        record_relationship_event("active")
    except Exception as _rel_exc:
        logger.debug("maturity relationship active tracking failed: %s", _rel_exc)

    # Maturity: award XP for completing a conversation turn
    try:
        from services.personality.maturity_engine import award_xp as _turn_award_xp
        _turn_award_xp(3, reason="conversation_turn")
    except Exception:
        pass

    # Persist routing telemetry (local-only) for debugging misroutes and regressions.
    try:
        rd = state.get("route_decision") if isinstance(state.get("route_decision"), dict) else {}
        from layla.memory.routing_telemetry import log_route_telemetry

        log_route_telemetry(
            conversation_id=str(state.get("conversation_id") or "") or None,
            goal=str(state.get("original_goal") or state.get("goal") or ""),
            task_type=str(rd.get("task_type") or ""),
            is_meta_self=bool(rd.get("is_meta_self")),
            has_workspace_signals=bool(rd.get("has_workspace_signals")),
            decision_action=str((state.get("last_decision") or {}).get("action") or ""),
            decision_tool=str((state.get("last_decision") or {}).get("tool") or ""),
            preflight_ok=state.get("preflight_ok") if "preflight_ok" in state else None,
            preflight_reason=str(state.get("preflight_reason") or "") or None,
            final_status=str(state.get("status") or "") or None,
            parse_failed=bool(state.get("status") == "parse_failed"),
        )
    except Exception as e:
        logger.debug("agent_loop: %s", e)

    emit_run_telemetry_fn(state, state.get("status") in ("finished", "plan_completed"))

    # Response envelope (stable keys for UI/API consumers).
    try:
        if state.get("status") in ("finished", "plan_completed"):
            state["steps_taken"] = list(state.get("steps") or [])
            if "completion_gate_passed" not in state:
                state["completion_gate_passed"] = True
            if "retry_count" not in state:
                state["retry_count"] = int(state.get("completion_gate_retries") or 0)
    except Exception as e:
        logger.debug("agent_loop: %s", e)
