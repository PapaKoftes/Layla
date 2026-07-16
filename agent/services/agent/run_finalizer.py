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
    auto_extract_learnings_fn: Callable,
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
        # Emotional presence (BL-190): nudge mood from this turn — the user's sentiment (praise /
        # correction / frustration) and a failed task outcome. Previously mood only ever moved from
        # the (unsurfaced) 👍/👎 UI, so it stayed permanently neutral and mood_hint injected nothing.
        try:
            if runtime_safety_module.load_config().get("emotional_presence_enabled", True):
                from services.personality.emotional_presence import register_from_turn
                _ev = state.get("outcome_evaluation") or {}
                _succ = _ev.get("success") if isinstance(_ev, dict) else None
                register_from_turn(str(goal or ""), outcome_success=_succ)
        except Exception as _mood_exc:
            logger.debug("emotional_presence turn nudge failed: %s", _mood_exc)
        try:
            from layla.memory.distill import run_distill_after_outcome
            run_distill_after_outcome(n=50)
        except Exception as e:
            logger.debug("distill after outcome failed: %s", e)
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
        # Auto-learning: extract and persist 1-2 insights from every substantive exchange
        final_text = ""
        for s in reversed(state.get("steps", [])):
            if s.get("action") == "reason":
                r = s.get("result", "")
                final_text = r if isinstance(r, str) else ""
                break
        # Sanitize before extracting. `final_text` above is the RAW `reason` step; the /agent router
        # only applies the bleed strip when building the text it SHOWS. That asymmetry meant the user
        # read a clean reply while the extractor ate whatever the model had regurgitated of its own
        # system prompt — and stored it as a "learning". Rows like "This is a written TEXT chat: you
        # are typing, not speaking…" (a byte-exact system_head_builder line) and "**Voice Contract**:
        # Blunt and surgical…" got in this way, then fed back through the KG block into later prompts.
        # This is not symptom-filtering: the extractor was reading the wrong variable. The real source
        # (a 3B model failing _OUTPUT_DISCIPLINE) is not fixable here.
        # A wrongly-emptied learning is just a skipped learning, so the strip is safe to apply here even
        # where it would be too aggressive for a user-facing reply.
        try:
            from services.agent.response_builder import clean_reply_text
            learn_text = clean_reply_text(
                final_text, status=state.get("status", "finished"), active_aspect=active_aspect
            )
        except Exception as _clean_exc:  # never let sanitation break the run
            logger.debug("learning sanitation failed, skipping extraction: %s", _clean_exc)
            learn_text = ""
        if learn_text and not state.get("refused") and len(learn_text.strip()) >= 80:
            import threading as _t
            _t.Thread(
                target=auto_extract_learnings_fn,
                args=(state.get("original_goal", ""), learn_text, active_aspect.get("id", "")),
                daemon=True,
                name="auto-learn",
            ).start()
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
    # Conversation entity extraction: extract entities from every exchange for codex/wiki
    _conv_final_text = ""
    try:
        for _cs in reversed(state.get("steps", [])):
            if _cs.get("action") == "reason":
                _csr = _cs.get("result", "")
                _conv_final_text = _csr if isinstance(_csr, str) else ""
                break
    except Exception as e:
        logger.debug("agent_loop: %s", e)
    if _conv_final_text and not state.get("refused"):
        try:
            from services.memory.conversation_entity_extractor import extract_in_background as _conv_ent_bg
            _conv_ent_bg(
                state.get("original_goal", ""),
                _conv_final_text,
                conversation_id=str(state.get("conversation_id", "")),
                aspect_id=active_aspect.get("id", ""),
            )
        except Exception as _cee_err:
            logger.debug("conversation_entity_extractor hook failed: %s", _cee_err)

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
