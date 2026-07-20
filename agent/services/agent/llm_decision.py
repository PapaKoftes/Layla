"""
LLM decision-making for the agent loop.

Builds the structured prompt and calls the LLM (outlines -> instructor ->
plain completion fallback) to obtain a JSON decision dictating the next
agent action (tool, reason, or think).

Also contains helper functions that are tightly coupled to the decision
pipeline: tool-set resolution (``get_tools_for_goal``) and recovery-hint
formatting (``format_recovery_hint_for_prompt``).

Extracted from agent_loop.py -- Phase 2 decomposition.
"""
from __future__ import annotations

import functools
import logging
from typing import Any

logger = logging.getLogger("layla")


# ---------------------------------------------------------------------------
# Helper: format recovery hint for the decision prompt
# ---------------------------------------------------------------------------

def format_recovery_hint_for_prompt(recovery_hint: dict) -> str:
    from services.infrastructure.failure_recovery import format_recovery_hint_for_prompt as _impl
    return _impl(recovery_hint)


# ---------------------------------------------------------------------------
# Helper: resolve the valid tool set for a given goal
# ---------------------------------------------------------------------------

def get_tools_for_goal(
    goal: str,
    *,
    context: str = "",
    workspace_root: str = "",
    state: dict | None = None,
    tools_registry: dict,
    valid_tools_all: frozenset,
) -> frozenset:
    """
    Return tool names for this turn.  Applies OpenClaw-style tool_policy
    (profile, tools_allow/deny, groups) then intent-based subset when
    tool_routing_enabled.
    """
    import runtime_safety

    try:
        cfg = runtime_safety.load_config()
        from services.tools.intent_router import route_intent
        from services.tools.tool_policy import (
            deterministic_route_tools_for_task_type,
            resolve_effective_tools_for_route,
        )

        skip_intent = not cfg.get("tool_routing_enabled", True)
        rd = None
        if state is not None and isinstance(state, dict):
            existing = state.get("route_decision")
            if isinstance(existing, dict) and (state.get("original_goal") or state.get("goal")) == goal:
                rd = existing
        if rd is None:
            rd = route_intent(goal, context=context, workspace_root=workspace_root)
            if state is not None and isinstance(state, dict):
                state["route_decision"] = rd.to_dict()
        else:
            # convert back into an object-like shape for downstream
            from services.tools.intent_router import RouteDecision
            rd = RouteDecision(**rd)
        names = set(resolve_effective_tools_for_route(cfg, rd, goal, tools_registry, skip_intent_filter=skip_intent))
        try:
            det = deterministic_route_tools_for_task_type(cfg, rd.task_type, tools_registry)
            if det:
                names = set(names) & set(det)
        except Exception as e:
            logger.warning("deterministic_route_tools failed: %s", e)
        # Deterministic routing: prefer a stable chain for common goal types.
        try:
            from services.tools.toolchain_graph import deterministic_toolchain_route

            route = deterministic_toolchain_route(goal or "")
            allowed = set(route.get("allowed_tools") or [])
            if allowed:
                names = (names & allowed) | {"reason", "read_file", "list_dir", "search_memories", "save_note"}
        except Exception as e:
            logger.warning("deterministic_toolchain_route failed: %s", e)
        # Visibility cap (default 15) when routing narrows by intent.
        try:
            cap = int(cfg.get("tool_visibility_cap", 15) or 15)
        except (TypeError, ValueError):
            cap = 15
        cap = max(8, min(30, cap))
        if cfg.get("tool_routing_enabled", True) and len(names) > cap:
            try:
                from layla.tools.registry import tool_recommend

                rec = tool_recommend(goal)
                top_n = max(1, cap - 5)
                top = [
                    r.get("tool")
                    for r in (rec.get("recommendations") or [])[: max(15, top_n + 6)]
                    if r.get("tool") in names
                ]
                names = set(top[:top_n]) | {"reason", "read_file", "list_dir", "search_memories", "save_note"}
            except Exception as e:
                logger.debug("tool_recommend visibility cap failed: %s", e, exc_info=True)
                top_n = max(1, cap - 5)
                names = set(list(names)[:top_n]) | {"reason", "read_file", "list_dir", "search_memories", "save_note"}
        # BL-205: drop tools whose gating `feature` is disabled, so the model never
        # sees (or wastes prompt tokens on, or picks) a tool that would only refuse at
        # call-time. Fail-open — any resolution error leaves the set untouched.
        names = _drop_disabled_feature_tools(names, tools_registry, cfg)
        # Same reasoning one step further out: a tool whose optional library is not installed
        # cannot work either, and offering it is worse than wasting tokens — it is what makes
        # her answer "yes, I can search the web" when every search backend is absent.
        names = _drop_missing_dependency_tools(names, tools_registry)
        return frozenset(names)
    except Exception as e:
        logger.warning("_get_tools_for_goal failed, returning all tools: %s", e)
        return valid_tools_all


def _drop_disabled_feature_tools(names: set, tools_registry: dict, cfg: dict) -> set:
    """Remove tools whose registry `feature` tag is not in the enabled feature set."""
    try:
        from install.setup_profiles import enabled_feature_ids
        enabled = set(enabled_feature_ids(cfg))
    except Exception:
        return names  # fail-open: never hide tools on a resolution error
    kept = set()
    for n in names:
        meta = tools_registry.get(n) or {}
        feat = meta.get("feature") if isinstance(meta, dict) else None
        if feat and feat not in enabled:
            continue
        kept.add(n)
    # never let the filter strip the core reasoning tools
    return kept | ({"reason"} & set(names))


@functools.lru_cache(maxsize=256)
def _module_installed(mod: str) -> bool:
    """Is an optional dependency importable? Cached — find_spec walks the path on every call."""
    try:
        import importlib.util

        return importlib.util.find_spec(mod) is not None
    except Exception:
        # A namespace/partial package can raise here. Treat as present: fail-open, so a probe
        # error degrades to today's behaviour (tool offered, refuses at call time) rather than
        # silently amputating a working tool.
        return True


def _drop_missing_dependency_tools(names: set, tools_registry: dict) -> set:
    """Remove tools whose registry `requires` module is not importable.

    These tools are still REGISTERED (registry.TOOLS is unchanged, so skill packs and the tool
    count stay stable) — they are only withheld from the set the model is shown, exactly like
    the `feature` filter above. Without this, every web/search tool is declared unconditionally
    on a box where none of the backing libraries are installed, so the model is told it can
    search the web and only discovers otherwise by calling a tool that returns
    "duckduckgo-search not installed".
    """
    kept = set()
    for n in names:
        meta = tools_registry.get(n) or {}
        req = meta.get("requires") if isinstance(meta, dict) else None
        if req and not _module_installed(str(req)):
            continue
        kept.add(n)
    return kept | ({"reason"} & set(names))


# ---------------------------------------------------------------------------
# Main entry point: build prompt and obtain LLM decision
# ---------------------------------------------------------------------------

def llm_decision(
    goal: str,
    state: dict,
    context: str,
    active_aspect: dict,
    show_thinking: bool,
    conversation_history: list,
    *,
    format_steps_fn,
    tools_registry: dict,
    valid_tools_all: frozenset,
) -> dict | None:
    """
    Ask the model for a structured decision: action (tool|reason), tool name,
    objective_complete.  Returns parsed dict or None to fall back to
    classify_intent.

    NOTE (P5-4): The extraction/parsing logic in this function has been
    refactored into ``services.llm_decision`` using a strategy pattern
    (OutlinesStrategy, InstructorStrategy, PlainJsonStrategy).  That module
    provides ``extract_decision()`` as an alternative entry point that
    accepts the fully-assembled prompt and valid_tools set.  This original
    function is kept for backward compatibility; the prompt-construction
    logic above the extraction call remains here since it depends on agent
    state, aspects, routing hints, and config.
    """
    import orchestrator
    import runtime_safety
    from decision_schema import parse_decision as _parse_decision
    from services.llm.llm_gateway import run_completion

    steps_text = format_steps_fn(state.get("steps") or [])
    objective = (state.get("objective") or goal).strip()
    steps_summary = str(state.get("steps_summary") or "").strip()
    if steps_summary:
        prompt_context = f"Objective: {objective[:500]}\n\n{steps_summary[:1200]}\n\n"
        if steps_text:
            prompt_context += f"Recent tool results (uncompressed tail):\n{steps_text[:900]}\n\n"
    elif steps_text:
        prompt_context = f"Objective: {objective[:500]}\n\nTool results so far:\n{steps_text[:1200]}\n\n"
    else:
        prompt_context = f"Objective: {objective[:800]}\n\n"
    sub_goals = state.get("sub_goals") or []
    if sub_goals:
        prompt_context += "Sub-objectives (guide tool choice): " + "; ".join(sub_goals[:3]) + "\n\n"

    # Cognitive workspace: chosen approach from multi-strategy deliberation
    cw = state.get("cognitive_workspace") or {}
    if cw.get("strategy_hint"):
        prompt_context += f"Chosen approach ({cw.get('chosen_name', '')}): {cw['strategy_hint']}\n\n"

    # File probe awareness (planning-only): surface hints without forcing a hard stop.
    try:
        cm = state.get("context_memory") or {}
        hints = cm.get("file_probe_hints") or {}
        if hints:
            lines = []
            for p, hs in list(hints.items())[:3]:
                if isinstance(hs, list) and hs:
                    lines.append(f"- {p}: " + " ".join(str(x)[:160] for x in hs[:2]))
            if lines:
                prompt_context += "File probe hints:\n" + "\n".join(lines) + "\n\n"
    except Exception as _exc:
        logger.debug("llm_decision: file_probe_hints: %s", _exc, exc_info=False)

    try:
        from services.tools.intent_routing_hints import tool_routing_prompt_hints

        _route_goal = (state.get("original_goal") or goal or "").strip()
        _rh = tool_routing_prompt_hints(_route_goal)
        if _rh:
            prompt_context += _rh
    except Exception as _exc:
        logger.debug("llm_decision: intent_routing_hints: %s", _exc, exc_info=False)

    aspect_block = ""
    if show_thinking:
        try:
            aspects = orchestrator._load_aspects()
            roster = getattr(orchestrator, "_DELIBERATION_ROSTER", ["morrigan", "nyx", "echo"])
            for aid in roster[:3]:
                a = next((x for x in aspects if x.get("id") == aid), None)
                if a and aid != active_aspect.get("id"):
                    name = a.get("name", aid)
                    role = (a.get("role") or a.get("voice") or "")[:60]
                    aspect_block += f"{name}: {role}\n"
            if aspect_block:
                aspect_block = "Aspects may suggest a tool; unify to one decision.\n" + aspect_block + "\n"
        except Exception as _exc:
            logger.debug("llm_decision: aspect_block: %s", _exc, exc_info=False)

    bias = orchestrator.get_decision_bias(active_aspect)
    bias_hint = ""
    if bias:
        try:
            bias_hint = orchestrator.decision_bias_prompt_extension(bias)  # richer, concrete nudges
        except Exception as e:
            logger.debug("decision_bias_prompt_extension failed: %s", e, exc_info=True)
            bias_hint = f"Decision bias: {', '.join(bias)}. Prefer tools and approach that match.\n"

    # Layla v3: observation mode (trial phase). In the early phases, bias toward answering/learning
    # unless the operator explicitly asked for action.
    observation_hint = ""
    try:
        cfg_obs = runtime_safety.load_config()
        if cfg_obs.get("observation_mode_enabled", True):
            from services.personality.familiarity import knows_operator

            # Keyed on KNOWLEDGE, not rank. This asked is_early_phase(ms.phase), and phase is
            # phase_for_rank(rank), so the restraint lifted at rank 6 — caution you wore off by
            # accumulating XP from tool calls and study sessions, none of which taught her
            # anything about the operator. Observation mode means "I don't know this person yet",
            # so it now reads the familiarity roster directly (the same substitution
            # familiarity_line made for the rank<1 directive in system_head_builder).
            # A blank profile reads False -> restraint stays on, which is the safe direction.
            if not knows_operator():
                _goal_l = (goal or "").lower()
                explicit_action = any(
                    kw in _goal_l
                    for kw in (
                        "write ",
                        "edit ",
                        "modify ",
                        "apply patch",
                        "replace_in_file",
                        "run ",
                        "execute ",
                        "install ",
                        "delete ",
                        "remove ",
                        "create file",
                        "add file",
                        "commit",
                        "push",
                    )
                )
                if not explicit_action:
                    observation_hint = (
                        "Observation mode (early phase): prefer action=\"reason\" (explain, ask clarifiers, learn). "
                        "Choose action=\"tool\" only if explicitly requested or necessary to answer.\n"
                    )
    except Exception as _exc:
        logger.debug("llm_decision: observation_hint failed: %s", _exc, exc_info=False)

    route_hint = ""
    try:
        rd = state.get("route_decision") if isinstance(state, dict) else None
        hints = (rd or {}).get("routing_hints") if isinstance(rd, dict) else None
        if isinstance(hints, list) and hints:
            route_hint = "Routing hints:\n- " + "\n- ".join(str(x)[:220] for x in hints[:4]) + "\n"
    except Exception as _exc:
        logger.debug("llm_decision: route_hint failed: %s", _exc, exc_info=False)

    no_progress_hint = ""
    try:
        from services.tools.tool_loop_detection import consume_prompt_hint

        _tlh = consume_prompt_hint(state)
        if _tlh:
            no_progress_hint += f"[Loop guard] {_tlh} "
    except Exception as _exc:
        logger.debug("llm_decision: loop_detection: %s", _exc, exc_info=False)
    last_ver = state.get("last_verification")
    if last_ver and not last_ver.get("progress_made") and last_ver.get("retry_suggested"):
        no_progress_hint += "Last tool step did not make progress; consider a different approach or reply (reason). "
    if state.get("environment_aligned") is False:
        no_progress_hint += "Environment check did not confirm success; consider different approach or reply (reason). "
    # North Star «8: failure awareness (structured hint stringified here)
    rh = state.get("recovery_hint")
    if rh and isinstance(rh, dict):
        no_progress_hint += format_recovery_hint_for_prompt(rh)
    consecutive = state.get("consecutive_no_progress", 0)
    if consecutive >= 2:
        shift_count = state.get("strategy_shift_count", 0)
        if shift_count == 1:
            last_tool = state.get("last_tool_used") or "unknown"
            no_progress_hint += (
                f"Strategy shift: try a different class of action. Avoid repeating the same tool (last was {last_tool}). "
                "Prefer high-impact inspection tools: read_file, grep_code, git_diff. "
            )
        else:
            no_progress_hint += "Several steps made no progress; consider replying (reason) to explain or suggest next steps. "

    reframe_candidate = (
        consecutive >= 2
        and state.get("strategy_shift_count", 0) >= 2
        and not state.get("objective_complete")
    )
    reframe_instruction = ""
    if reframe_candidate:
        reframe_instruction = (
            "Alternatively propose a revised objective to solve the right problem: "
            'add "revised_objective": "one clear sentence" to your JSON. '
            "Prefer reframing toward higher-impact, achievable objective. "
            "If you reframe, we will continue with the new objective. "
        )

    priority_context = ""
    prev_priority = state.get("priority_level")
    prev_risk = state.get("risk_estimate")
    if prev_priority or prev_risk:
        priority_context = f"Previous step priority: {prev_priority or 'unknown'}. "
        if prev_priority == "low":
            priority_context += "Avoid low-impact retries; prefer higher-impact pivots or reply (reason). "
        else:
            priority_context += "Prefer high-impact pivots. "
        if prev_risk and "high" in str(prev_risk).lower():
            priority_context += "Risk was high; bias toward safer paths (read_file, list_dir, grep_code, git_*). "
        elif prev_priority:
            priority_context += "When risk is high prefer safer paths (read, inspect). "

    cfg_pre = runtime_safety.load_config()
    mcp_tool_hint = ""
    if cfg_pre.get("mcp_client_enabled") and cfg_pre.get("mcp_inject_tool_summary_in_decisions"):
        try:
            from services.infrastructure.mcp_client import get_cached_mcp_tool_summary_for_prompt

            mcp_tool_hint = get_cached_mcp_tool_summary_for_prompt(cfg_pre)
        except Exception as e:
            logger.debug("mcp_tool_summary_for_prompt failed: %s", e, exc_info=True)
            mcp_tool_hint = ""
    if mcp_tool_hint:
        prompt_context = prompt_context + mcp_tool_hint + "\n\n"

    # Skill packs: without this line the model never learns an installed pack exists and
    # will never pick run_skill_pack. Gated on the same execution flag as the tool, so a
    # disabled install is not advertised as a capability.
    if cfg_pre.get("skill_packs_execute_enabled"):
        try:
            from services.skills.skill_packs import installed_summary_for_prompt

            skill_pack_hint = installed_summary_for_prompt(cfg_pre)
        except Exception as e:
            logger.debug("skill pack prompt summary failed: %s", e, exc_info=True)
            skill_pack_hint = ""
        if skill_pack_hint:
            prompt_context = prompt_context + skill_pack_hint + "\n\n"

    valid_tools = get_tools_for_goal(
        goal,
        context=context,
        workspace_root=state.get("workspace_root") or "",
        state=state,
        tools_registry=tools_registry,
        valid_tools_all=valid_tools_all,
    )
    # Decision policy caps: enforce safety/verify gates and tool restrictions at the prompt boundary.
    try:
        if cfg_pre.get("decision_policy_enabled", True):
            from services.safety.decision_policy import (
                apply_caps_to_valid_tools as _apply_caps_to_valid_tools,
            )
            from services.safety.decision_policy import (
                build_policy_caps as _build_policy_caps,
            )
            _cid = (state.get("conversation_id") or "").strip() or "unknown"
            _caps = _build_policy_caps(state, cfg_pre, conversation_id=_cid)
            state["policy_caps"] = _caps.to_trace_dict()
            valid_tools = _apply_caps_to_valid_tools(valid_tools, _caps)
    except Exception as _dp_exc:
        logger.debug("decision_policy caps skipped: %s", _dp_exc)
    from services.prompts.prompt_builder import build_decision_tool_hints

    tools_list, _edit_hint_pb = build_decision_tool_hints(valid_tools, goal)
    think_trace_hint = ""
    if show_thinking:
        think_trace_hint = (
            'For action "think", put the plan in "thought" as 2-4 numbered lines ("1." "2." …), '
            "one short sentence each — restate aim, outline the next move, note gaps/risks (ChatGPT-style step trace).\n"
        )
    _edit_hint = _edit_hint_pb
    tool_first_hint = ""
    if cfg_pre.get("tool_first_enforcement_enabled") and not observation_hint:
        if not state.get("tool_attempted_this_turn") and not state.get("objective_complete"):
            tool_first_hint = (
                "Tool-first policy: for substantive questions about code, files, or the workspace, prefer action=\"tool\" "
                "with a read-only inspection tool before action=\"reason\".\n"
            )
    pipeline_debug_hint = ""
    if str(state.get("pipeline_stage") or "") == "DEBUG" and cfg_pre.get("pipeline_enforcement_enabled", True):
        pipeline_debug_hint = (
            "Pipeline DEBUG: stagnation recovery — narrow the next tool (different path or verify with read_file/grep) "
            "before repeating writes or shell.\n"
        )
    prompt = (
        f"{aspect_block}"
        f"{bias_hint}"
        f"{observation_hint}"
        f"{route_hint}"
        f"{tool_first_hint}"
        f"{pipeline_debug_hint}"
        f"{prompt_context}"
        f"{priority_context}"
        f"{no_progress_hint}"
        f"{reframe_instruction}"
        f"{think_trace_hint}"
        f"{_edit_hint}"
        "Choose exactly one: reply (reason), internal plan (think), or run one tool. "
        f"Available actions/tools: {tools_list}. "
        "Output exactly one JSON line, no other text. "
        'Format: {"action":"tool","tool":"read_file","priority_level":"high"} or {"action":"think","thought":"..."} or {"action":"reason","objective_complete":true}. '
        'Examples: {"action":"reason","priority_level":"medium","objective_complete":true} '
        '{"action":"tool","tool":"read_file","args":{"path":"agent/main.py"},"priority_level":"high","objective_complete":false} '
        '{"action":"think","thought":"Suspect the failure is in router mounting; inspect main.py includes.","priority_level":"medium"}. '
        "Include priority_level: \"low\" or \"medium\" or \"high\" for the chosen action. "
        "Optionally impact_estimate, effort_estimate, risk_estimate (brief). "
        "Use objective_complete true only when you have enough to answer.\n"
    )
    try:
        cfg_tmp = runtime_safety.load_config()
        if cfg_tmp.get("decision_few_shot_enabled", True):
            prompt += (
                "Few-shot examples (copy the shape, adapt tool/args):\n"
                '{"action":"reason","thought":"I have enough context to answer.","priority_level":"medium","objective_complete":true}\n'
                '{"action":"tool","tool":"read_file","args":{"path":"agent/main.py"},"priority_level":"high","objective_complete":false}\n'
                '{"action":"tool","tool":"grep_code","args":{"pattern":"def _llm_decision","path":"agent"},"priority_level":"medium","objective_complete":false}\n'
                '{"action":"reason","thought":"Operator asked about Layla (capabilities/identity). Reply directly without tools.","priority_level":"medium","objective_complete":true}\n'
            )
    except Exception as e:
        logger.debug("decision few_shot config load failed: %s", e, exc_info=True)
    prev_override = None
    try:
        cfg = runtime_safety.load_config()
        # Optionally route decision JSON generation to a dedicated structured-output model.
        from services.llm.llm_gateway import get_model_override, set_model_override

        try:
            prev_override = get_model_override()
            if (cfg.get("decision_model") or "").strip():
                set_model_override("decision")
        except Exception as e:
            logger.warning("decision model override setup failed: %s", e)

        max_tok = 120 if reframe_candidate else (220 if show_thinking else 80)
        use_instructor = cfg.get("use_instructor_for_decisions", True)
        structured_on = bool(cfg.get("structured_generation_enabled", True))
        # Native GBNF constrained decoding — zero extra dependency (llama.cpp's own
        # grammar sampler). Pins action/priority to their enums and `tool` to the exact
        # valid-tool set, so a small model cannot emit an unparseable decision or a
        # hallucinated tool. First choice on a local model; falls through to
        # outlines/instructor/plain on any miss.
        if bool(cfg.get("gbnf_decoding_enabled", True)) and not (cfg.get("llama_server_url") or "").strip():
            try:
                from services.llm.gbnf_grammar import run_gbnf_agent_decision
                from services.llm.llm_gateway import _get_llm

                _llm_g = _get_llm()
                if _llm_g is not None:
                    from services.llm.self_consistency import (
                        majority_decision,
                        self_consistency_samples,
                    )

                    _k = self_consistency_samples(cfg)
                    if _k > 1:
                        # Self-consistency: sample the constrained decision K times at a
                        # higher temperature and keep the modal (action, tool). Costs K×
                        # inference — high-stakes only; off by default (K=1).
                        _samples = [
                            run_gbnf_agent_decision(
                                _llm_g, prompt, max_tokens=max_tok, temperature=0.6, valid_tools=valid_tools
                            )
                            for _ in range(_k)
                        ]
                        _gd = majority_decision([s for s in _samples if s is not None])
                    else:
                        _gd = run_gbnf_agent_decision(
                            _llm_g, prompt, max_tokens=max_tok, temperature=0.1, valid_tools=valid_tools
                        )
                    if _gd is not None:
                        return _gd
            except Exception as _exc:
                logger.debug("llm_decision: gbnf constrained decode skipped: %s", _exc, exc_info=False)
        # Optional outlines + llama-cpp (wheels on 3.11—3.12); no-op if package missing
        if structured_on and not (cfg.get("llama_server_url") or "").strip():
            try:
                from services.llm.llm_gateway import _get_llm
                from services.llm.structured_gen import run_outlines_agent_decision

                _llm_local = _get_llm()
                if _llm_local is not None:
                    _od = run_outlines_agent_decision(
                        _llm_local,
                        prompt,
                        max_tokens=max_tok,
                        temperature=0.1,
                        valid_tools=valid_tools,
                    )
                    if _od is not None:
                        return _od
            except Exception as _exc:
                logger.debug("llm_decision: structured_gen outlines skipped: %s", _exc, exc_info=False)
        # Try instructor (grammar-constrained JSON) when local Llama available
        if use_instructor:
            for _attempt in range(2):  # 1 retry before falling back
                try:
                    import instructor

                    from decision_schema import AgentDecision
                    if not (cfg.get("llama_server_url") or "").strip():
                        from services.llm.llm_gateway import _get_llm
                        llm = _get_llm()
                        if llm is not None:
                            create = instructor.patch(
                                create=llm.create_chat_completion_openai_v1,
                                mode=instructor.Mode.JSON_SCHEMA,
                            )
                            decision_obj = create(
                                messages=[{"role": "user", "content": prompt}],
                                max_tokens=max_tok,
                                temperature=0.1,
                                response_model=AgentDecision,
                            )
                            d = decision_obj.model_dump()
                            action = (d.get("action") or "reason").lower()
                            if action not in ("tool", "reason", "think"):
                                action = "reason"
                            tool = (d.get("tool") or "").strip() or None
                            if action in ("think",):
                                tool = None
                            if action == "tool" and tool and tool not in valid_tools:
                                tool = None
                            d["action"] = action
                            d["tool"] = tool
                            return d
                except Exception as e:
                    logger.debug("instructor decision attempt failed: %s", e)
        # Fallback: plain completion + parse
        retry_prompt_suffix = " Output only a single JSON line, no other text or commentary.\n"
        for attempt in range(2):
            out = run_completion(
                prompt + (retry_prompt_suffix if attempt > 0 else ""),
                max_tokens=max_tok,
                temperature=0.1,
                stream=False,
            )
            if isinstance(out, dict):
                text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or (out.get("choices") or [{}])[0].get("text") or ""
            else:
                text = ""
            text = (text or "").strip()
            decision = _parse_decision(text, valid_tools)
            if decision is not None:
                return decision
        return None
    except Exception as e:
        logger.warning("llm_decision parse failed: %s", e)
        return None
    finally:
        try:
            from services.llm.llm_gateway import set_model_override

            set_model_override(prev_override)
        except Exception as e:
            logger.debug("llm_decision set_model_override cleanup failed: %s", e, exc_info=True)
