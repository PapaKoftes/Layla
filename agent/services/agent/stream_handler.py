"""
Streaming response handler for the agent loop.

Extracted from agent_loop.py — Phase 2 decomposition.
Contains stream_reason (outer entry point) and _stream_reason_body (inner generator).
"""
from __future__ import annotations

import json as _json_delib
import logging
import re
import threading

logger = logging.getLogger("layla")

# Constant: placeholder used when sanitizing conversation history to hide
# system prompt leaks or junk replies from the model's recent-conversation view.
_SANITIZED_PLACEHOLDER: str = "[...]"

# Cross-request reasoning-mode smoothing -- shared with the non-streaming path.
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


def get_last_reasoning_mode() -> str:
    """Return the shared last reasoning mode."""
    return _rstate_get()


def set_last_reasoning_mode(value: str) -> None:
    """Set the shared last reasoning mode."""
    _rstate_set(value)


def stream_reason(
    goal: str,
    context: str = "",
    conversation_history: list = None,
    aspect_id: str = "",
    show_thinking: bool = False,
    model_override: str | None = None,
    skip_self_reflection: bool = False,
    reasoning_mode_override: str | None = None,
    precomputed_recall: str | None = None,
    persona_focus: str = "",
    workspace_root: str = "",
    cognition_workspace_roots: list[str] | None = None,
    budget_retrieval_depth: str = "",
):
    """
    Build the same prompt as the reason path and yield token strings from streaming completion.
    Used when the client requests stream=True; no refusal/earned_title parsing.
    Sets model ContextVar for this generator (autonomous_run clears it before streaming).
    """
    import runtime_safety
    from services.llm.llm_gateway import reset_active_aspect, set_active_aspect, set_model_override

    set_model_override(model_override)
    if not model_override:
        try:
            _cfg_route = runtime_safety.load_config()
            if _cfg_route.get("tool_routing_enabled", True):
                from services.llm.model_router import classify_task_for_routing, is_routing_enabled

                if is_routing_enabled():
                    set_model_override(classify_task_for_routing(goal, context or "", _cfg_route))
        except Exception as _exc:
            logger.debug("agent_loop:L591: %s", _exc, exc_info=False)
    # Expose the active aspect so a per-aspect model override can win in the gateway.
    _asp_tok = set_active_aspect(aspect_id)
    try:
        yield from _stream_reason_body(
            goal,
            context,
            conversation_history,
            aspect_id,
            show_thinking,
            skip_self_reflection,
            reasoning_mode_override=reasoning_mode_override,
            precomputed_recall=precomputed_recall,
            persona_focus=persona_focus,
            workspace_root=workspace_root,
            cognition_workspace_roots=cognition_workspace_roots,
        )
    finally:
        set_model_override(None)
        reset_active_aspect(_asp_tok)


def _stream_reason_body(
    goal: str,
    context: str = "",
    conversation_history: list = None,
    aspect_id: str = "",
    show_thinking: bool = False,
    skip_self_reflection: bool = False,
    reasoning_mode_override: str | None = None,
    precomputed_recall: str | None = None,
    persona_focus: str = "",
    workspace_root: str = "",
    cognition_workspace_roots: list[str] | None = None,
):
    """Inner generator: prompt + streaming tokens (model override set by stream_reason)."""
    import orchestrator
    import runtime_safety
    from services.agent.response_builder import (
        is_junk_reply as _is_junk_reply,
    )
    from services.agent.response_builder import (
        iter_with_response_pacing as _iter_with_response_pacing,
    )
    from services.llm.llm_gateway import get_stop_sequences, run_completion
    from services.prompts.system_head_builder import (
        build_system_head as _build_system_head,
    )
    from services.prompts.system_head_builder import (
        semantic_recall as _semantic_recall,
    )

    active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
    # Classify reasoning need for the streaming path (same logic as the non-streaming path).
    # This gates expensive _build_system_head ops so "hi" doesn't trigger ChromaDB + graph + workspace.
    if reasoning_mode_override in {"none", "light", "deep"}:
        _stream_rmode = str(reasoning_mode_override)
    else:
        try:
            from services.infrastructure.reasoning_classifier import classify_reasoning_need, stabilize_reasoning_mode

            _stream_rmode = classify_reasoning_need(goal, context or "")
            _cfg_sr = runtime_safety.load_config()
            if _stream_rmode == "deep" and (_cfg_sr.get("performance_mode") or "").strip().lower() in ("low",):
                _stream_rmode = "light"
            with _reason_mode_lock:
                _stream_rmode = stabilize_reasoning_mode(_rstate_get(), _stream_rmode)
                _rstate_set(_stream_rmode)
        except Exception as e:
            logger.warning("stream reasoning_classifier failed: %s", e)
            _stream_rmode = "light"
    _stream_recall = precomputed_recall or ""
    if not _stream_recall and goal and _stream_rmode != "none":
        try:
            _stream_recall = _semantic_recall(goal, k=runtime_safety.load_config().get("semantic_k", 5)).strip()
        except Exception as _exc:
            logger.warning("agent_loop:L648: %s", _exc, exc_info=True)
    head = _build_system_head(
        goal=goal,
        aspect=active_aspect,
        workspace_root=workspace_root or "",
        conversation_history=conversation_history or [],
        reasoning_mode=_stream_rmode,
        _precomputed_recall=_stream_recall,
        persona_focus_id=(persona_focus or "").strip().lower(),
        cognition_workspace_roots=cognition_workspace_roots,
    )
    convo_block = ""
    try:
        convo_turns = max(0, int(runtime_safety.load_config().get("convo_turns", 0)))
    except (TypeError, ValueError):
        convo_turns = 0
    if convo_turns > 0 and conversation_history:
        name = active_aspect.get("name", "Layla")
        turns = conversation_history[-convo_turns:]
        n_turns = len(turns)
        lines = []
        for i, t in enumerate(turns):
            role = t.get("role", "")
            # Recent turns (last 2) get more context; older turns are compressed.
            turns_from_end = n_turns - i
            max_chars = 600 if turns_from_end <= 2 else 220
            content_t = (t.get("content") or "")[:max_chars].strip()
            if role == "user":
                lines.append(f"User: {content_t}")
            else:
                if "system is under load" in content_t.lower():
                    content_t = "I couldn't reply just then."
                elif (content_t.startswith("[") and "You are" in content_t) or ("you are layla" in content_t.lower() and ("use the identity" in content_t.lower() or "rules below" in content_t.lower())):
                    content_t = _SANITIZED_PLACEHOLDER
                elif _is_junk_reply(content_t):
                    content_t = _SANITIZED_PLACEHOLDER
                lines.append(f"{name}: {content_t}")
        convo_block = "\n".join(lines)

    # Multi-aspect debate engine: if deliberation_mode is not "solo", route through
    # the debate engine for a 3-phase pipeline (generate -> critique -> synthesize).
    # The debate engine runs non-streaming, so we yield the final response in one shot.
    cfg = runtime_safety.load_config()  # noqa: F841
    _delib_mode = str(cfg.get("deliberation_mode", "solo")).strip().lower()
    _delib_routed = False
    # "auto" stays safe (solo-equivalent) until the governor auto-cap (UPG-14) decides —
    # only EXPLICIT debate/council/tribunal force the multi-model engine. (Was: any
    # non-solo, so the schema-default "auto" debated every turn + bypassed tools/approvals.)
    if _delib_mode not in ("solo", "auto") and not cfg.get("skip_deliberation"):
        try:
            from services.planning.debate_engine import run_deliberation as _run_delib
            _delib_result = _run_delib(
                goal=goal,
                state={},
                cfg=cfg,
                mode=_delib_mode,
            )
            if _delib_result.mode != "solo":
                _delib_routed = True
                # Yield deliberation metadata as a special JSON-prefixed line
                # so the SSE handler can extract it for the UI.
                _delib_meta = _json_delib.dumps({
                    "__deliberation__": True,
                    "mode": _delib_result.mode,
                    "participating_aspects": _delib_result.participating_aspects,
                    "aspect_responses": _delib_result.aspect_responses or {},
                    "critiques": _delib_result.critiques or {},
                    "synthesis_notes": _delib_result.synthesis_notes or "",
                })
                yield f"__DELIB_META__{_delib_meta}__DELIB_END__"
                yield _delib_result.final_response or ""
        except Exception as _delib_exc:
            logger.debug("debate_engine streaming route failed, falling back: %s", _delib_exc)

    if _delib_routed:
        return

    temperature = cfg.get("temperature", 0.2)
    max_tok = cfg.get("completion_max_tokens", 256)
    # Phatic turns ("hi", "thanks", "how are you") get a SHORT, warm reply — cap generation
    # hard so the small model can't ramble into a wall of text or drift theatrical after it
    # has already answered (the first sentence is fine; the last 150 tokens are where "the
    # abyss calls to us…" creeps in). Substantive short questions ("who are you") are NOT
    # lightweight, so they keep the full budget.
    try:
        from services.prompts.system_head_builder import is_lightweight_chat_turn as _is_light
        if _is_light(goal, _stream_rmode):
            max_tok = min(int(max_tok or 256), int(cfg.get("chat_light_max_tokens", 80) or 80))
    except Exception:
        pass
    stop = get_stop_sequences()

    # Thinking mode: an explicit show_thinking (or the enabled deliberation flag) runs ONE
    # multi-POV pass. The synthesized CONCLUSION is the reply the user sees; the per-aspect
    # POV lines go ONLY into the collapsible thinking trace — never stitched into the reply.
    # (The old bug: build_deliberation_prompt's six "[⚔ MORRIGAN] …" scaffold lines streamed
    # straight into the bubble, so a reply read as ~6 stitched answers.)
    deliberate = bool(show_thinking) or orchestrator.should_deliberate(goal, active_aspect)
    if deliberate:
        yield from _stream_deliberation(
            goal=goal, active_aspect=active_aspect, context=context,
            head=head, convo_block=convo_block,
            temperature=temperature, max_tok=max_tok, stop=stop,
        )
        return

    prompt = orchestrator.build_standard_prompt(
        message=goal, aspect=active_aspect, context=context,
        head=head, convo_block=convo_block,
    )
    gen = run_completion(prompt, max_tokens=max_tok, temperature=temperature, stream=True, stop=stop)
    try:
        _pace_ms = int(cfg.get("response_pacing_ms", 0) or 0)
    except (TypeError, ValueError):
        _pace_ms = 0
    gen = _iter_with_response_pacing(gen, _pace_ms)
    buffer = ""
    held_tokens: list[str] = []   # tokens held while we check for JSON blob start
    _json_suppressed = False
    _PROMPT_ECHO_RE = re.compile(r"(?:^|\n)\s*(##\s*(TASK|CONTEXT|SCRATCHPAD|REPO)\b|Current goal\s*:|\[Active aspect\s*:|Last user message\s*:|Repo snapshot\s*:|Repo structure\s*:)", re.IGNORECASE | re.MULTILINE)
    # A section header can also leak MID-LINE ("… here?  ## SYSTEM\n\n<repeats prompt>"), which
    # the line-anchored pattern above misses. Case-SENSITIVE: an ALL-CAPS section name is
    # unambiguously scaffold, whereas a natural '## Context' heading is title-case.
    _PROMPT_ECHO_MIDLINE_RE = re.compile(r"#{1,3}[ \t]*(?:SYSTEM|TASK|CONTEXT|SCRATCHPAD|REPO|OBJECTIVE|INSTRUCTIONS)\b")
    for token in gen:
        buffer += token
        if any(s in buffer for s in stop):
            break
        # Stop streaming if model starts echoing system prompt markers (line-anchored or mid-line)
        _echo_m = _PROMPT_ECHO_RE.search(buffer) or _PROMPT_ECHO_MIDLINE_RE.search(buffer)
        if _echo_m:
            m = _echo_m
            clean = buffer[:m.start()].strip()
            if held_tokens:
                # Still in the initial buffer phase — yield clean text, discard junk tokens
                held_tokens.clear()
                if clean and not _is_junk_reply(clean):
                    yield clean
            buffer = clean
            break
        # Hold tokens until we know the reply isn't a raw decision-JSON blob.
        # Decision blobs start with '{' → we hold up to 120 chars before committing.
        if not held_tokens and not _json_suppressed:
            held_tokens.append(token)
            if len(buffer) < 120:
                continue  # keep buffering to check
            # Enough chars: decide
            if _is_junk_reply(buffer):
                _json_suppressed = True
                held_tokens.clear()
                continue
            # Not junk → flush held tokens
            for t in held_tokens:
                yield t
            held_tokens.clear()
        elif held_tokens:
            # Still accumulating during the check window
            held_tokens.append(token)
            if len(buffer) >= 120:
                if _is_junk_reply(buffer):
                    _json_suppressed = True
                    held_tokens.clear()
                else:
                    for t in held_tokens:
                        yield t
                    held_tokens.clear()
        elif not _json_suppressed:
            yield token
    # Flush any remaining held tokens (short replies that never hit 120 chars)
    if held_tokens and not _is_junk_reply(buffer):
        for t in held_tokens:
            yield t


def _stream_deliberation(
    *,
    goal: str,
    active_aspect: dict,
    context: str,
    head: str,
    convo_block: str,
    temperature: float,
    max_tok: int,
    stop: list,
):
    """Run one multi-POV deliberation pass and yield (trace-meta, then reply).

    The reply the user sees is the synthesized CONCLUSION only. The per-aspect POV lines
    are parsed out and emitted as ``__DELIB_META__…__DELIB_END__`` — the SSE layer turns
    that into the collapsible thinking trace and never puts it in the reply body.

    Buffered on purpose: the conclusion is produced AFTER the POV block, so there's nothing
    stream-able until the whole pass finishes. Thinking mode is the explicit "take your
    time" mode, so trading live tokens for a clean single-voice answer is the right call.
    """
    import orchestrator
    from services.agent.response_builder import is_junk_reply as _is_junk_reply
    from services.llm.llm_gateway import run_completion
    from services.prompts.system_head_builder import (
        enrich_deliberation_context as _enrich_deliberation_context,
    )
    prompt = orchestrator.build_deliberation_prompt(
        message=goal, active_aspect=active_aspect,
        context=_enrich_deliberation_context(context),
    )
    if head:
        prompt = head + "\n\n" + prompt
    if convo_block:
        prompt = prompt + f"\n\nRecent conversation:\n{convo_block}"

    # Room for N short POV lines + the conclusion (the standard 256 cap truncates the answer).
    try:
        delib_max = max(int(max_tok or 256), 512)
    except (TypeError, ValueError):
        delib_max = 512
    concluder_name = str((active_aspect or {}).get("name", "") or "")

    raw_parts: list[str] = []
    try:
        for token in run_completion(
            prompt, max_tokens=delib_max, temperature=temperature, stream=True, stop=stop
        ):
            raw_parts.append(token)
            if any(s in "".join(raw_parts[-4:]) for s in stop):
                break
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("deliberation completion failed: %s", exc)
    raw = "".join(raw_parts)

    reply, aspect_responses = orchestrator.split_deliberation_output(raw, concluder_name)

    # Emit the thinking trace (only if we actually parsed distinct POVs — else it's just a
    # normal answer and there's nothing to show in the trace).
    if aspect_responses:
        _meta = {
            "__deliberation__": True,
            "mode": "tribunal",  # all aspects contributed; UI label = "✦ Tribunal"
            "participating_aspects": list(aspect_responses.keys()),
            "aspect_responses": aspect_responses,
            "critiques": {},
            "synthesis_notes": "",
        }
        yield f"__DELIB_META__{_json_delib.dumps(_meta, ensure_ascii=False)}__DELIB_END__"

    reply = (reply or "").strip()
    if reply and not _is_junk_reply(reply):
        yield reply
