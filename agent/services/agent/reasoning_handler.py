"""Handle the 'reason' intent: LLM completion, refusal, reflection, earned
title, research redirect, polish, initiative, completion gate.

Extracted from agent_loop._autonomous_run_impl_core (lines 2413-2686) to
reduce module size.
"""
from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)


def handle_reasoning_intent(
    state: dict,
    run_params: dict,
    goal: str,
    context: str,
    conversation_history: list,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue,
    persona_focus_id: str,
) -> tuple[str, str]:
    """Handle the 'reason' intent.

    Returns ``(updated_goal, flow)`` where *flow* is one of:
    - ``"break"`` -- caller should break out of the decision loop
    - ``"continue"`` -- caller should continue the loop
    - ``"return"`` -- caller should ``return state`` immediately (stream_pending)
    """
    import agent_loop as _al
    import orchestrator
    import runtime_safety
    from services.infrastructure.output_polish import polish_output as _polish_output
    from services.prompts.system_head_builder import (
        build_system_head as _build_system_head,
    )
    from services.prompts.system_head_builder import (
        enrich_deliberation_context as _enrich_deliberation_context,
    )

    # Use run_completion through agent_loop's namespace so tests can monkeypatch it.
    run_completion = _al.run_completion

    active_aspect = run_params["active_aspect"]
    cfg = run_params["cfg"]
    workspace = run_params["workspace"]
    _precomputed_recall = run_params["_precomputed_recall"]
    _dignity_boundary_prompt = run_params["_dignity_boundary_prompt"]
    temperature = run_params["temperature"]

    # ------------------------------------------------------------------
    # Stream pending fast-return
    # ------------------------------------------------------------------
    if stream_final:
        state["status"] = "stream_pending"
        state["goal_for_stream"] = goal
        state["reasoning_mode_for_stream"] = state.get("reasoning_mode", "light")
        state["precomputed_recall_for_stream"] = _precomputed_recall
        state["stream_workspace_root"] = workspace
        state["cognition_workspace_roots_for_stream"] = state.get("cognition_workspace_roots") or []
        return goal, "return"

    # ------------------------------------------------------------------
    # Section 1: context compression
    # ------------------------------------------------------------------
    effective_history = conversation_history or []
    if effective_history and cfg.get("context_compression", True) and state.get("reasoning_mode") != "none":
        try:
            from services.context.context_manager import (
                effective_compact_threshold_ratio,
                summarize_history,
            )

            n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
            ratio = effective_compact_threshold_ratio(cfg, n_ctx)
            keep = int(cfg.get("context_sliding_keep_messages", 0) or 0)
            if cfg.get("context_aggressive_compress_enabled") and keep <= 0:
                keep = 10
            effective_history = summarize_history(
                effective_history,
                n_ctx=n_ctx,
                threshold_ratio=ratio,
                keep_recent_messages=keep,
            )
        except Exception as _exc:
            logger.debug("agent_loop:L3972: %s", _exc, exc_info=False)

    # ------------------------------------------------------------------
    # LLMLingua / heuristic per-message compression
    # ------------------------------------------------------------------
    if effective_history and cfg.get("llmlingua_compression_enabled", False):
        try:
            from services.prompts.prompt_compressor import compress_conversation_history

            n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
            _keep_recent = max(4, int(cfg.get("context_sliding_keep_messages", 4) or 4))
            effective_history = compress_conversation_history(
                effective_history,
                keep_recent=_keep_recent,
                token_budget=max(800, int(n_ctx * 0.3)),
            )
        except Exception as _cmp_e:
            logger.debug("llmlingua history compress failed: %s", _cmp_e)

    # ------------------------------------------------------------------
    # Build system head
    # ------------------------------------------------------------------
    head = _build_system_head(
        goal=goal,
        aspect=active_aspect,
        workspace_root=workspace,
        sub_goals=state.get("sub_goals"),
        state=state,
        conversation_history=effective_history,
        reasoning_mode=state.get("reasoning_mode", "light"),
        _precomputed_recall=_precomputed_recall,
        persona_focus_id=persona_focus_id,
        cognition_workspace_roots=state.get("cognition_workspace_roots"),
        packed_context=state.get("packed_context") if isinstance(state.get("packed_context"), dict) else None,
    )

    # Dignity injection
    if _dignity_boundary_prompt:
        head = head.rstrip() + "\n\n" + _dignity_boundary_prompt

    # ------------------------------------------------------------------
    # Conversation block formatting
    # ------------------------------------------------------------------
    convo_block = ""
    try:
        convo_turns = max(0, int(cfg.get("convo_turns", 0)))
    except (TypeError, ValueError):
        convo_turns = 0
    if convo_turns > 0 and effective_history:
        name = active_aspect.get("name", "Layla")
        turns = effective_history[-convo_turns:]
        n_turns = len(turns)
        lines = []
        for i, t in enumerate(turns):
            role = t.get("role", "")
            turns_from_end = n_turns - i
            max_chars = 600 if turns_from_end <= 2 else 220
            content_t = (t.get("content") or "")[:max_chars].strip()
            if role == "user":
                lines.append(f"User: {content_t}")
            else:
                if "system is under load" in content_t.lower():
                    content_t = "I couldn't reply just then."
                elif (content_t.startswith("[") and "You are" in content_t) or (
                    "you are layla" in content_t.lower()
                    and ("use the identity" in content_t.lower() or "rules below" in content_t.lower())
                ):
                    content_t = _al._SANITIZED_PLACEHOLDER
                elif _al._is_junk_reply(content_t):
                    content_t = _al._SANITIZED_PLACEHOLDER
                lines.append(f"{name}: {content_t}")
        convo_block = "\n".join(lines)

    # ------------------------------------------------------------------
    # Multi-aspect debate engine
    # ------------------------------------------------------------------
    _delib_mode = str(cfg.get("deliberation_mode", "solo")).strip().lower()
    _delib_routed = False
    text = ""
    deliberate = False
    # "auto" is solo-equivalent until the governor decides (see stream_handler); only
    # explicit debate/council/tribunal force the multi-model engine.
    if _delib_mode not in ("solo", "auto"):
        try:
            from services.planning.debate_engine import run_deliberation as _run_delib

            _delib_result = _run_delib(
                goal=goal,
                state=state,
                cfg=cfg,
                mode=_delib_mode,
            )
            if _delib_result.mode != "solo":
                text = _delib_result.final_response or ""
                deliberate = True
                _delib_routed = True
                state["deliberation_result"] = {
                    "mode": _delib_result.mode,
                    "participating_aspects": _delib_result.participating_aspects,
                    "synthesis_notes": _delib_result.synthesis_notes,
                }
        except Exception as _delib_exc:
            logger.debug("debate_engine route failed, falling back to standard: %s", _delib_exc)

    # ------------------------------------------------------------------
    # Deliberation / standard prompt + LLM completion
    # ------------------------------------------------------------------
    if not _delib_routed:
        # Parity with the STREAMING path (stream_handler.py:250): show_thinking IS the thinking mode —
        # it runs the single-call multi-POV deliberation whose conclusion is the reply and whose POV
        # lines go into the collapsible trace (project memory: "deliberation IS the thinking mode").
        # This branch previously omitted show_thinking, so an identical {show_thinking:true} request
        # deliberated when streamed but returned a plain single-pass answer when non-streamed (audit #5).
        deliberate = bool(show_thinking) or orchestrator.should_deliberate(goal, active_aspect)
        if deliberate:
            prompt = orchestrator.build_deliberation_prompt(
                message=goal,
                active_aspect=active_aspect,
                context=_enrich_deliberation_context(context),
            )
            if head:
                prompt = head + "\n\n" + prompt
            if convo_block:
                prompt = prompt + f"\n\nRecent conversation:\n{convo_block}"
        else:
            prompt = orchestrator.build_standard_prompt(
                message=goal,
                aspect=active_aspect,
                context=context,
                head=head,
                convo_block=convo_block,
            )

        max_tok = cfg.get("completion_max_tokens", 256)
        if deliberate:
            # Floor the budget the SAME way the streaming path does (stream_handler.py:370): the
            # deliberation prompt seeds ~6 "[⚔ NAME] (cue): …" POV lines BEFORE "[CONCLUSION — NAME]:",
            # so the standard 256 cap is exhausted by the scaffold and the conclusion is truncated away —
            # split_deliberation_output then returns "" and the caller shows its "No response" standby,
            # losing the deliberated answer. 512 leaves room for the POV lines + the conclusion.
            try:
                max_tok = max(int(max_tok or 256), 512)
            except (TypeError, ValueError):
                max_tok = 512
        # Expose the active aspect so a per-aspect model override (aspect_model_overrides)
        # can win in the gateway's model resolution. Leak-safe: reset in finally.
        from services.llm.llm_gateway import reset_active_aspect, set_active_aspect
        _asp_tok = set_active_aspect(active_aspect.get("id"))
        try:
            out = run_completion(prompt, max_tokens=max_tok, temperature=temperature, stream=False)
        finally:
            reset_active_aspect(_asp_tok)
        if isinstance(out, str):
            out = {"choices": [{"text": out}]}
        if isinstance(out, dict):
            text = (out.get("choices") or [{}])[0].get("text") or (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        else:
            text = ""
        text = (text or "").strip()
        text = _al.truncate_at_next_user_turn(text)
        if deliberate:
            # Separate the conclusion from the multi-aspect POV scaffold — parity with the streaming
            # _stream_deliberation path. Without this the raw "[⚔ NAME] (cue): …" block (and the
            # stitched per-aspect answers) leaked verbatim as the reply. A missing/empty conclusion
            # returns "" so the caller substitutes its standby rather than the scaffold.
            try:
                _concl, _ = orchestrator.split_deliberation_output(text, active_aspect.get("name") or "")
                text = _concl
            except Exception:
                pass

    text = _al._clean_response_text(text)

    # ------------------------------------------------------------------
    # Refusal detection
    # ------------------------------------------------------------------
    refused = False
    refusal_reason = ""
    if active_aspect.get("can_refuse") or active_aspect.get("will_refuse"):
        m = re.match(r"^\s*\[REFUSED:\s*(.+?)\]\s*", text, re.DOTALL | re.IGNORECASE)
        if m:
            refusal_reason = m.group(1).strip()
            text = re.sub(r"^\s*\[REFUSED:\s*.+?\]\s*", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
            refused = True
    state["refused"] = refused
    state["refusal_reason"] = refusal_reason

    # ------------------------------------------------------------------
    # Reflection injection
    # ------------------------------------------------------------------
    if state.get("reflection_pending") and not state.get("reflection_asked") and text:
        text = text.rstrip() + "\n\nDoes this direction align with your goals?"
        state["reflection_asked"] = True

    # ------------------------------------------------------------------
    # Earned title parsing
    # ------------------------------------------------------------------
    et_match = re.search(r"\[EARNED_TITLE:\s*(.+?)\]\s*$", text, re.IGNORECASE)
    if et_match:
        # Only persist a title the USER actually granted (the prompt says titles come
        # "if the user says you earned a title"). Without this gate a small model
        # self-awards a hallucinated title (e.g. "Water Wizard"), it gets injected into
        # every later prompt, and the model fixates on it — derailing even a plain "hello".
        _ug = (goal or "").lower()
        _user_granted = any(
            kw in _ug for kw in (
                "you earned", "you've earned", "you have earned", "i grant", "i dub",
                "your title", "you are now", "i name you", "i'll call you", "call you",
                "award you", "bestow", "title of",
            )
        )
        if _user_granted:
            try:
                from layla.memory.db import save_earned_title

                save_earned_title(active_aspect.get("id", ""), et_match.group(1).strip())
            except Exception as _exc:
                logger.debug("agent_loop:L4130: %s", _exc, exc_info=False)
        else:
            logger.debug("earned-title self-award ignored (user did not grant): %s", et_match.group(1).strip()[:40])
        text = re.sub(r"\s*\[EARNED_TITLE:\s*.+?\]\s*$", "", text, flags=re.IGNORECASE).strip()

    # ------------------------------------------------------------------
    # Research mission redirect
    # ------------------------------------------------------------------
    if state.get("research_lab_root") and not refused and state.get("status") != "timeout":
        if _al._research_response_asks_user(text):
            goal = (
                state["original_goal"]
                + "\n\n[Tool results so far]:\n"
                + _al._format_steps(state["steps"])
                + "\n\n[System: Your last response asked the user a question. In this mission you must not ask questions. Produce the full structured output now: System Understanding, Weakness Map, Upgrade Opportunities, Lens Case Study, Suggested Roadmap.]"
            )
            return goal, "continue"

    # ------------------------------------------------------------------
    # Output polish
    # ------------------------------------------------------------------
    text = _polish_output(text, cfg)

    # ------------------------------------------------------------------
    # Context attribution (default on) — attribute the reply to the memory it drew on, so the UI
    # can show provenance. Makes the previously-dead context_attribution_enabled flag live.
    # ------------------------------------------------------------------
    try:
        if cfg.get("context_attribution_enabled", True) and text and (_precomputed_recall or "").strip():
            from services.context.context_attribution import attribute_response, persist_attributions
            _attr = attribute_response(
                text,
                [{"id": "memory_recall", "label": "Recalled memory", "content": _precomputed_recall}],
                cfg=cfg,
            )
            _rid = str(state.get("execution_id") or "")
            if _rid:
                persist_attributions(_rid, _attr)
    except Exception as _ce:
        logger.debug("context_attribution skipped: %s", _ce)

    # ------------------------------------------------------------------
    # Initiative suggestion
    # ------------------------------------------------------------------
    try:
        cfg_inline = runtime_safety.load_config()
        if cfg_inline.get("inline_initiative_enabled", False):
            # NO PHASE TEST. This used to require is_high_trust_phase(ms.phase), and phase comes
            # from phase_for_rank(), so ranks 0-5 were "awakening"/"attunement" and the feature
            # was suppressed until rank 6 — i.e. until the operator had ground out ~19,500 XP of
            # unrelated activity. Driven on this operator's live state (rank 2,
            # inline_initiative_enabled=True in their config): the switch was on and the
            # suggestion never appended. A setting the operator has turned on must do the thing.
            # Rank/XP is an activity odometer; it is not permission and no longer decides this.
            from services.infrastructure.initiative_inline import maybe_append_inline_suggestion

            text = maybe_append_inline_suggestion(text, state=state, cfg=cfg_inline)
    except Exception as _exc:
        logger.debug("agent_loop:inline_initiative failed: %s", _exc, exc_info=False)

    # ------------------------------------------------------------------
    # Completion gate
    # ------------------------------------------------------------------
    try:
        cfg_gate = runtime_safety.load_config()
        if bool(cfg_gate.get("completion_gate_enabled", False)):
            from services.infrastructure.output_quality import passes_completion_gate

            ok_gate, reasons = passes_completion_gate(goal=state.get("original_goal") or goal, text=text, state=state, cfg=cfg_gate)
            state["completion_gate_passed"] = bool(ok_gate)
            state["completion_gate_reasons"] = reasons[:6]
            try:
                max_r = int(cfg_gate.get("completion_gate_max_retries", 1) or 1)
            except (TypeError, ValueError):
                max_r = 1
            max_r = max(0, min(2, max_r))
            cur_r = int(state.get("completion_gate_retries") or 0)
            if not ok_gate and cur_r < max_r and state.get("status") != "timeout":
                state["completion_gate_retries"] = cur_r + 1
                state.setdefault("steps", []).append(
                    {
                        "action": "completion_gate",
                        "result": {
                            "ok": False,
                            "reason": "completion_gate_failed",
                            "reasons": reasons[:6],
                            "retry": True,
                        },
                    }
                )
                goal = (
                    (state.get("original_goal") or goal)
                    + "\n\n[System: Your last response failed the completion gate for these reasons: "
                    + ", ".join(reasons[:4])
                    + ". Produce a correct, complete response now. Do not restate the goal.]\n"
                )
                return goal, "continue"
            if not ok_gate and cur_r >= max_r:
                text = (
                    "I couldn't meet the completion quality gate within the retry budget.\n\n"
                    "Structured failure:\n"
                    f"- reasons: {', '.join(reasons[:6]) or 'unknown'}\n"
                    "- suggested_next: simplify the request, reduce scope, or provide a specific file/path/expected output.\n"
                )
    except Exception as _exc:
        logger.debug("completion gate failed open: %s", _exc, exc_info=False)

    # ------------------------------------------------------------------
    # Append step + finish
    # ------------------------------------------------------------------
    state["steps"].append({
        "action": "reason",
        "result": text,
        "deliberated": deliberate,
        "aspect": active_aspect.get("id"),
    })
    state["status"] = "finished"

    # Save Echo aspect memory
    if text and not refused:
        try:
            from services.infrastructure.outcome_writer import _maybe_save_session_pattern_memory

            _maybe_save_session_pattern_memory(
                aspect_id=active_aspect.get("id", ""),
                user_msg=state["original_goal"],
                reply=text,
                conversation_history=conversation_history or [],
            )
        except Exception as _exc:
            logger.debug("agent_loop:L4163: %s", _exc, exc_info=False)

    return goal, "break"
