"""
Lightweight planning engine: break complex goals into executable steps.
Uses LLM to produce a structured plan (3–6 steps); each step has task + suggested tools.
Supports agent roles: planner, executor, researcher, debugger, memory_curator.
"""
import json
import logging
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger("layla")

# Keyword args forwarded to agent_loop.autonomous_run (must stay in sync with its signature).
_AUTONOMOUS_KW_KEYS = frozenset({
    "context",
    "workspace_root",
    "allow_write",
    "allow_run",
    "conversation_history",
    "aspect_id",
    "show_thinking",
    "stream_final",
    "ux_state_queue",
    "research_mode",
    "plan_depth",
    "model_override",
    "reasoning_effort",
    "priority",
    "persona_focus",
    "conversation_id",
    "cognition_workspace_roots",
    "client_abort_event",
    "background_progress_callback",
    "active_plan_id",
    "plan_approved",
    "skip_engineering_pipeline",
    "engineering_pipeline_mode",
    "clarification_reply",
    "resume_execution_state",
    "coordinator_trace",
    "context_files",
})


def _filter_autonomous_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if k in _AUTONOMOUS_KW_KEYS}


def _synthetic_step_for_exec_row(s: dict[str, Any]) -> Any:
    role = str(s.get("role") or "").strip().lower()
    valid = frozenset({"analysis", "planning", "refactor", "edit", "test", "build", "cad", "research"})
    if role in valid:
        stype = role
    elif role in ("", "task"):
        stype = "analysis"
    else:
        stype = "analysis"
    tl = s.get("tools") if isinstance(s.get("tools"), list) else []
    tools = [str(t).strip() for t in tl if str(t).strip()]
    auto_filled = bool(s.get("_tools_auto_filled") or s.get("tools_auto_filled"))
    vh = s.get("validation_hint")
    sc = s.get("success_criteria")
    return SimpleNamespace(
        type=stype,
        id=str(s.get("step", "")),
        tools=tools,
        tools_auto_filled=auto_filled,
        validation_hint=str(vh).strip() if isinstance(vh, str) else "",
        success_criteria=str(sc).strip() if isinstance(sc, str) else "",
    )


def _run_agent_step(
    agent_run_fn: Any,
    step_goal: str,
    base_kwargs: dict[str, Any],
    tools_list: list[str],
) -> dict[str, Any]:
    """Set thread-local tool allowlist when tools_list non-empty; filter kwargs for autonomous_run."""
    from services.engine_plans import _is_low_quality
    from services.tool_allowlist_context import clear_plan_step_tool_allowlist, set_plan_step_tool_allowlist

    names = [str(t).strip() for t in (tools_list or []) if str(t).strip()]
    if names:
        set_plan_step_tool_allowlist(frozenset(names))
    else:
        clear_plan_step_tool_allowlist()
    try:
        kw = _filter_autonomous_kwargs(base_kwargs)
        r1 = agent_run_fn(step_goal, **kw)
        if _is_low_quality(r1):
            improve = f"Improve this answer:\n{r1.get('response', '')}\nBe precise and concise."
            return agent_run_fn(improve, **kw)
        return r1
    finally:
        clear_plan_step_tool_allowlist()

ROLE_TOOL_HINTS = {
    "researcher": "Prefer: ddg_search, fetch_article, wiki_search, arxiv_search",
    "debugger": "Prefer: grep_code, python_ast, read_file, run_python",
    "memory_curator": "Prefer: search_memories, save_note, get_project_context",
}


def get_tool_reliability_hint() -> str:
    """Return hint string for tools with higher success rate (tool outcome learning)."""
    try:
        from layla.memory.db import get_tool_reliability
        stats = get_tool_reliability()
        if not stats:
            return ""
        # Top 3 by success_rate * avg_quality, min 5 outcomes
        ranked = [
            (name, s["success_rate"] * (s["avg_quality"] or 0.5))
            for name, s in stats.items()
            if s.get("count", 0) >= 3
        ]
        ranked.sort(key=lambda x: -x[1])
        top = [n for n, _ in ranked[:5] if n]
        slow = [
            name
            for name, st in stats.items()
            if st.get("count", 0) >= 5 and float(st.get("avg_latency", 0) or 0) > 8000
        ]
        hint = ""
        if top:
            hint = f"Higher reliability (from past outcomes): {', '.join(top)}"
        if slow[:4]:
            slow_bit = "High-latency tools (plan buffers): " + ", ".join(slow[:4])
            hint = hint + ("\n" if hint else "") + slow_bit
        return hint or ""
    except Exception:
        pass
    return ""


def get_tool_low_reliability_warning() -> str:
    """Warn about tools with enough samples and low success — planning should add verification."""
    try:
        from layla.memory.db import get_tool_reliability

        stats = get_tool_reliability()
        bad = [
            n
            for n, s in stats.items()
            if s.get("count", 0) >= 5 and float(s.get("success_rate", 1.0) or 0.0) < 0.45
        ]
        if bad:
            return (
                "Lower reliability (from past outcomes) — plan a read/verify step before relying on: "
                + ", ".join(bad[:8])
            )
    except Exception:
        pass
    return ""


def personality_planner_bias(aspect_id: str) -> str:
    """Map active aspect to planner ordering / depth nudges (North Star §11–13)."""
    aid = (aspect_id or "morrigan").strip().lower()
    if aid == "morrigan":
        return (
            "Persona planner weight (Morrigan): increase effective planning depth — explicit verification "
            "after writes; keep steps minimal and shippable."
        )
    if aid == "nyx":
        return (
            "Persona planner weight (Nyx): increase exploration — allow an early broad read or map step "
            "before narrowing to edits."
        )
    if aid == "lilith":
        return (
            "Persona planner weight (Lilith): lower risk tolerance — prefer read-only steps first; "
            "mutate only after checks; call out approval-sensitive steps."
        )
    if aid == "echo":
        return "Persona planner weight (Echo): include one checkpoint step that ties work to the user's stated goal."
    if aid == "eris":
        return "Persona planner weight (Eris): one lateral or non-obvious step is acceptable if it reduces repeated failure."
    if aid == "cassandra":
        return "Persona planner weight (Cassandra): name the riskiest assumption in an early step."
    return ""


def build_planning_bias_prompt(
    conversation_id: str,
    aspect_id: str,
    cfg: dict | None,
    *,
    goal: str = "",
    preferred_strategy: str | None = None,
) -> str:
    """Prior-turn evaluation + recent tool failures + persona + toolchain hint for create_plan."""
    parts: list[str] = []
    try:
        from shared_state import get_last_outcome_evaluation

        ev = get_last_outcome_evaluation(conversation_id)
        if isinstance(ev, dict) and ev.get("score") is not None:
            iss = ev.get("issues") if isinstance(ev.get("issues"), list) else []
            parts.append(
                f"Last run outcome (heuristic): score={ev.get('score')}, success={ev.get('success')}. "
                f"Issues: {'; '.join(str(x) for x in iss[:5]) or 'none'}. "
                "Adjust steps to avoid repeating the same failure mode."
            )
            if ev.get("reason") and str(ev.get("reason")) != "ok":
                parts.append(f"Last run reason: {ev.get('reason')}.")
            imp = ev.get("improvement")
            if isinstance(imp, str) and imp.strip():
                parts.append(f"Suggested improvement: {imp.strip()[:400]}")
            if ev.get("confidence") is not None:
                parts.append(f"Outcome confidence (heuristic): {ev.get('confidence')}.")
            if ev.get("cost_score") is not None:
                parts.append(f"Cost-efficiency score (higher is better): {ev.get('cost_score')}.")
            m = ev.get("metrics")
            if isinstance(m, dict) and m.get("wall_time_seconds") is not None:
                parts.append(
                    f"Last run wall time ~{m.get('wall_time_seconds')}s, tool steps: {m.get('tool_step_count', '?')}."
                )
            try:
                from services.outcome_evaluation import policy_caps_trace_from_evaluation

                _caps_tr = policy_caps_trace_from_evaluation(ev)
                if _caps_tr.get("require_verify_before_mutate"):
                    parts.append(
                        "Structured policy from last outcome: require read/verify-class tools before mutating steps in this plan."
                    )
            except Exception:
                pass
    except Exception:
        pass
    try:
        from layla.memory.db import get_recent_tool_outcome_failures

        fails = get_recent_tool_outcome_failures(6)
        if fails:
            bits = []
            for r in fails[:5]:
                tn = r.get("tool_name") or "?"
                ctx = (r.get("context") or "")[:72]
                bits.append(f"{tn}" + (f" ({ctx})" if ctx else ""))
            parts.append("Recent tool failures (SQLite): " + "; ".join(bits) + ". Add verification or alternate tools.")
    except Exception:
        pass
    # Reinforced learnings: surface top high-confidence items so they influence next plan, not just storage.
    try:
        from layla.memory.db import get_top_learnings_for_planning

        top = get_top_learnings_for_planning(limit=5, min_confidence=0.66)
        if top:
            lines = []
            for r in top[:5]:
                txt = (r.get("content") or "").strip().replace("\n", " ")
                if len(txt) > 180:
                    txt = txt[:180].rsplit(" ", 1)[0] + "..."
                lid = r.get("id")
                c = r.get("confidence")
                lines.append(f"- (id={lid}, conf={c}) {txt}")
            parts.append("Reinforced learnings (high confidence; treat as constraints/priors):\n" + "\n".join(lines))
    except Exception:
        pass
    pb = personality_planner_bias(aspect_id)
    if pb:
        parts.append(pb)
    try:
        from services.toolchain_awareness import toolchain_planning_hint

        th = toolchain_planning_hint()
        if th:
            parts.append(th)
    except Exception:
        pass
    try:
        from services.toolchain_graph import planner_toolchain_cost_line

        cg = planner_toolchain_cost_line(goal)
        if cg:
            parts.append(cg)
    except Exception:
        pass
    ps = (preferred_strategy or "").strip()
    if ps:
        parts.append(
            "Learned strategy preference (from past task outcomes — honor when compatible): "
            f"{ps[:200]}."
        )
    return "\n".join(parts).strip()

PLAN_KEYWORDS = frozenset(
    {"analyze", "build", "research", "investigate", "plan", "implement", "refactor", "audit"}
)
MIN_GOAL_LEN = 80


def should_plan(goal: str, cfg: dict | None = None, plan_depth: int = 0, state: dict | None = None) -> bool:
    """True if goal warrants a structured plan (long or planning keywords). Respects max_plan_depth."""
    if cfg is not None and not cfg.get("planning_enabled", True):
        return False
    max_depth = int(cfg.get("max_plan_depth", 3)) if cfg else 3
    if plan_depth >= max_depth:
        return False
    # Recovery: replan bypasses length/keyword gate so macro-plan can restructure after stagnation.
    if state and str(state.get("recovery_strategy") or "") == "replan":
        return True
    g = (goal or "").strip().lower()
    if len(g) < MIN_GOAL_LEN:
        return False
    return any(kw in g for kw in PLAN_KEYWORDS)


def create_plan(
    goal: str,
    max_steps: int = 6,
    cfg: dict | None = None,
    prior_plans_digest: str = "",
    *,
    conversation_id: str = "",
    aspect_id: str = "",
    preferred_strategy: str | None = None,
    packed_context: dict | None = None,
) -> list[dict]:
    """
    Use LLM to produce a structured plan.
    Each step: {"step": int, "task": str, "tools": list[str]}
    Limit to 3–6 steps.
    """
    if not goal or not goal.strip():
        return []
    try:
        from services.plan_templates import fill_open_plan_steps, match_skeleton_plan, skeleton_with_open_slots

        sk = match_skeleton_plan(goal, cfg)
        if sk:
            return sk[:max_steps]
        sk2 = skeleton_with_open_slots(goal, cfg)
        if sk2:
            return fill_open_plan_steps(goal, sk2, max_steps=max_steps)[:max_steps]
    except Exception:
        pass
    try:
        from services.llm_gateway import run_completion
        tools_list = (
            "list_dir, read_file, grep_code, python_ast, security_scan, fetch_url, "
            "ddg_search, search_memories, write_file, apply_patch, workspace_map, "
            "project_discovery, geometry_extract_machining_ir, codex_suggest_update, fetch_article, wiki_search, arxiv_search"
        )
        skills_hint = ""
        try:
            from layla.skills.registry import get_skills_prompt_hint
            skills_hint = get_skills_prompt_hint(cfg)
        except Exception:
            pass
        reliability_hint = get_tool_reliability_hint()
        low_rel = get_tool_low_reliability_warning()
        extra_ctx = ""
        if (prior_plans_digest or "").strip():
            extra_ctx = f"\n{prior_plans_digest.strip()[:3500]}\n\n"
        bias_block = build_planning_bias_prompt(
            conversation_id or "",
            aspect_id or "",
            cfg,
            goal=goal[:2000],
            preferred_strategy=preferred_strategy,
        )
        pack_extra = ""
        if isinstance(packed_context, dict) and packed_context:
            mb = (packed_context.get("memory_block") or "").strip()[:2200]
            cb = (packed_context.get("code_text") or "").strip()[:1600]
            fb = (packed_context.get("files_text") or "").strip()[:1200]
            bits = []
            if mb:
                bits.append("Memory retrieval:\n" + mb)
            if cb:
                bits.append("Code retrieval:\n" + cb)
            if fb:
                bits.append("Pinned files (excerpts):\n" + fb)
            if bits:
                pack_extra = "\nStructured context from unified retrieval (use when relevant):\n" + "\n\n".join(bits) + "\n\n"
        prompt = (
            f"Given this goal:\n\n{goal[:800]}\n\n"
            f"{extra_ctx}"
            f"{pack_extra}"
            f"Produce a step-by-step plan. Output only a JSON array of objects. "
            f"Each object: {{\"step\": 1, \"task\": \"short description\", \"tools\": [\"tool1\", \"tool2\"]}}. "
            f"Use 3-6 steps. Choose tools from: {tools_list}. "
        )
        if reliability_hint:
            prompt += f"\n{reliability_hint}\n"
        if low_rel:
            prompt += f"\n{low_rel}\n"
        if bias_block:
            prompt += f"\nPlanning bias (past outcomes + persona + toolchain — honor when compatible):\n{bias_block}\n"
        if skills_hint:
            prompt += f"\n{skills_hint}\n"
        prompt += "Output only the JSON array, no other text."
        out = run_completion(prompt, max_tokens=400, temperature=0.2, stream=False)
        if not isinstance(out, dict):
            return []
        text = (
            (out.get("choices") or [{}])[0].get("message") or {}
        ).get("content", "") or (out.get("choices") or [{}])[0].get("text", "")
        if not text:
            return []
        m = re.search(r"\[[\s\S]*?\]", text)
        if not m:
            return []
        steps = json.loads(m.group(0))
        if not isinstance(steps, list):
            return []
        result = []
        for i, s in enumerate(steps[:max_steps]):
            if not isinstance(s, dict):
                continue
            task = (s.get("task") or s.get("description") or "").strip()
            tools = s.get("tools") or []
            if isinstance(tools, str):
                tools = [t.strip() for t in tools.split(",") if t.strip()]
            if not task:
                continue
            role = _infer_role(task)
            result.append({
                "step": i + 1,
                "task": task[:200],
                "tools": [str(t)[:60] for t in tools[:5]],
                "role": role,
            })
        return result[:6]
    except Exception:
        return []


def normalize_plan_steps_tools(plan: list[dict], cfg: dict | None) -> list[dict]:
    """
    When plan_governance_require_nonempty_step_tools is on: fill empty tools on analysis-like
    in-loop plan rows (create_plan shape) with plan_step_default_read_tools (must exist in TOOLS).
    Skips steps whose type/role is edit|test|build|refactor|cad (no silent widen).
    """
    if not plan or not cfg or not cfg.get("plan_governance_require_nonempty_step_tools"):
        return plan
    mutating = frozenset({"edit", "test", "build", "refactor", "cad"})
    raw_defaults = cfg.get("plan_step_default_read_tools")
    if not isinstance(raw_defaults, list) or not raw_defaults:
        raw_defaults = ["read_file", "list_dir", "grep_code"]
    try:
        from layla.tools.registry import TOOLS as _TOOLS

        allowed = [str(t).strip() for t in raw_defaults if str(t).strip() and str(t).strip() in _TOOLS]
    except Exception:
        allowed = [str(t).strip() for t in raw_defaults if str(t).strip()]
    if not allowed:
        allowed = ["read_file", "list_dir", "grep_code"]
    allowed = allowed[:12]
    for s in plan:
        if not isinstance(s, dict):
            continue
        role = str(s.get("role") or s.get("type") or "").strip().lower()
        if role in mutating:
            continue
        tools = s.get("tools") if isinstance(s.get("tools"), list) else []
        if tools:
            continue
        s["tools"] = list(allowed)
        s["_tools_auto_filled"] = True
    return plan


def _infer_role(task: str) -> str:
    """Infer agent role from task keywords. Returns role name or empty string."""
    t = (task or "").lower()
    if any(k in t for k in ("research", "search", "find", "look up", "investigate", "wiki", "article")):
        return "researcher"
    if any(k in t for k in ("debug", "fix", "trace", "error", "bug", "inspect", "diagnose")):
        return "debugger"
    if any(k in t for k in ("remember", "save", "store", "recall", "memory", "context", "project")):
        return "memory_curator"
    return ""


def run_governed_plan_step(
    step_row: dict[str, Any],
    step_goal: str,
    *,
    agent_run_fn: Any | None = None,
    agent_kwargs: dict[str, Any] | None = None,
    agent_result_fn: Any | None = None,
    default_max_retries: int = 1,
    retry_suffix_fn: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Single step with governance (allowlist, validate_step_outcome, retries).
    Shared by execute_plan and file-backed engine_plans.
    Either agent_result_fn(goal) -> dict (file-plan path) or agent_run_fn + agent_kwargs (SQLite path).
    """
    from services.plan_step_governance import low_confidence_response, validate_step_outcome

    ak = agent_kwargs if isinstance(agent_kwargs, dict) else {}
    dm = max(0, min(3, int(default_max_retries) if isinstance(default_max_retries, int) else 1))
    try:
        mr = int(step_row.get("max_retries", dm) or dm)
    except (TypeError, ValueError):
        mr = dm
    mr = max(0, min(3, mr))
    max_attempts = max(1, mr + 1)
    synth = _synthetic_step_for_exec_row(step_row)
    tools_hint = step_row.get("tools", [])
    if not isinstance(tools_hint, list):
        tools_hint = []

    if retry_suffix_fn is None:
        from services.plan_execution_prompts import sqlite_step_retry_suffix as _suffix

        retry_suffix_fn = _suffix

    try:
        import runtime_safety

        _cfg_gov = runtime_safety.load_config()
    except Exception:
        _cfg_gov = {}

    last: dict[str, Any] = {}
    success = False
    attempt = 0
    verr = ""
    refused = False
    lc = False
    try:
        for attempt in range(max_attempts):
            use_goal = step_goal
            suffix = retry_suffix_fn(attempt, mr) if attempt > 0 else ""
            if attempt > 0 and bool(_cfg_gov.get("autonomy_optimizer_enabled", False)):
                try:
                    from services.autonomy_optimizer import (
                        last_failed_tool_from_agent_response,
                        propose_step_recovery,
                    )

                    _failed_tool = last_failed_tool_from_agent_response(last)
                    if _failed_tool or verr:
                        _prop = propose_step_recovery(
                            failed_tool=_failed_tool,
                            validation_reason=verr,
                            step_tools=tools_hint,
                            cfg=_cfg_gov,
                        )
                        if _prop.get("action") == "suggest_tool" and _prop.get("tool"):
                            suffix += (
                                f"\n\n[Plan recovery hint: try `{_prop['tool']}` next — "
                                f"{str(_prop.get('rationale') or '').strip()[:400]}]"
                            )
                        elif _prop.get("action") == "retry" and _prop.get("rationale"):
                            suffix += f"\n\n[Plan recovery: {str(_prop.get('rationale'))[:400]}]"
                except Exception:
                    pass
            if attempt > 0:
                use_goal = step_goal + suffix
            if agent_result_fn is not None:
                last = agent_result_fn(use_goal)
            elif agent_run_fn is not None:
                last = _run_agent_step(agent_run_fn, use_goal, ak, tools_hint)
            else:
                last = {"status": "error", "response": "no_agent_fn", "refused": True}
            refused = bool(last.get("refused"))
            vok, verr = validate_step_outcome(synth, last)
            lc = low_confidence_response(last)
            if not refused and vok and not lc:
                success = True
                break
    except Exception as ex:
        last = {"status": "error", "response": str(ex), "refused": True}
        verr = f"executor_exception:{ex}"
        refused = True

    row = {
        "step": step_row.get("step"),
        "task": step_row.get("task", ""),
        "result_status": "ok" if success else "step_failed",
        "governance_ok": success,
        "validation_error": "" if success else (verr or ("low_confidence" if lc else "refused" if refused else "unknown")),
        "low_confidence": bool(not success and lc),
        "refused": bool(last.get("refused")),
        "attempts": attempt + 1,
        "agent_status": last.get("status", ""),
    }
    return row, last


def execute_plan(
    plan: list[dict],
    agent_run_fn: Any,
    goal_prefix: str = "",
    plan_depth: int = 0,
    *,
    step_governance: bool = False,
    default_max_retries: int = 1,
    progress_callback: Callable[[list[dict]], None] | None = None,
    **agent_kwargs: Any,
) -> dict:
    """
    Execute each plan step sequentially via agent_run_fn(step_goal, ...).
    agent_run_fn is autonomous_run or a compatible callable.
    plan_depth: current planning depth; steps run at plan_depth+1 to respect max_plan_depth.
    agent_kwargs: context, workspace_root, allow_write, allow_run, etc. (forwarded from caller)
    When step_governance=True (SQLite /plans execute): per-step tool allowlist, validate_step_outcome,
    low_confidence_response, bounded retries, and richer steps_done rows.
    Returns combined result with steps executed and final summary.
    """
    if not plan:
        return {"status": "no_plan", "steps_done": [], "summary": ""}
    defaults = {
        "context": "",
        "workspace_root": "",
        "allow_write": False,
        "allow_run": False,
        "conversation_history": [],
        "aspect_id": "morrigan",
        "show_thinking": False,
        "active_plan_id": "",
        "plan_approved": False,
    }
    defaults.update(agent_kwargs)
    defaults["plan_depth"] = plan_depth + 1  # enforce depth increment; agent_kwargs must not override

    dm = max(0, min(3, int(default_max_retries) if isinstance(default_max_retries, int) else 1))

    steps_done: list[dict[str, Any]] = []
    def _emit_progress() -> None:
        if not callable(progress_callback):
            return
        merged: list[dict[str, Any]] = []
        for idx, base in enumerate(plan):
            row = dict(base) if isinstance(base, dict) else {}
            if idx < len(steps_done):
                sd = steps_done[idx]
                row["execution_status"] = sd.get("result_status") or sd.get("agent_status") or ""
                row["result_summary"] = str(sd.get("error") or sd.get("validation_error") or "")[:500]
                if "governance_ok" in sd:
                    row["governance_ok"] = sd.get("governance_ok")
            merged.append(row)
        try:
            progress_callback(merged)
        except Exception:
            logger.debug("execute_plan progress_callback failed", exc_info=False)

    for s in plan:
        task = s.get("task", "")
        tools_hint = s.get("tools", [])
        if not isinstance(tools_hint, list):
            tools_hint = []
        role = s.get("role", "")
        step_goal = task
        if tools_hint:
            step_goal += f" (consider: {', '.join(str(t) for t in tools_hint[:3])})"
        if role and role in ROLE_TOOL_HINTS:
            step_goal += f" [{ROLE_TOOL_HINTS[role]}]"
        if goal_prefix:
            step_goal = f"{goal_prefix}\n\nStep {s.get('step', len(steps_done)+1)}: {step_goal}"

        if not step_governance:
            try:
                result = agent_run_fn(step_goal, **_filter_autonomous_kwargs(defaults))
                steps_done.append({
                    "step": s.get("step"),
                    "task": task,
                    "result_status": result.get("status", ""),
                })
            except Exception as e:
                steps_done.append({"step": s.get("step"), "task": task, "result_status": "error", "error": str(e)})
            _emit_progress()
            continue

        exec_row = {
            "step": s.get("step"),
            "task": task,
            "tools": tools_hint,
            "role": role,
            "max_retries": s.get("max_retries", dm),
            "validation_hint": str(s.get("validation_hint") or "").strip(),
            "success_criteria": str(s.get("success_criteria") or "").strip(),
        }
        done_row, _last = run_governed_plan_step(
            exec_row,
            step_goal,
            agent_run_fn=agent_run_fn,
            agent_kwargs=defaults,
            default_max_retries=dm,
        )
        done_row["task"] = task
        steps_done.append(done_row)
        _emit_progress()

    summary = "\n".join(f"{d.get('step')}. {d.get('task')}: {d.get('result_status', '')}" for d in steps_done)
    out: dict[str, Any] = {"status": "plan_completed", "steps_done": steps_done, "summary": summary}
    if step_governance:
        out["all_steps_ok"] = all(d.get("governance_ok") for d in steps_done)
    return out


def validate_plan_before_execution(
    plan: list[dict],
    *,
    cfg: dict | None,
    workspace_root: str = "",
) -> tuple[list[dict], bool, str]:
    """
    Deterministic plan pre-validation (cheap checks before execution).
    Returns (normalized_plan, ok, reason).
    """
    if not isinstance(plan, list) or not plan:
        return [], False, "empty_plan"
    c = cfg or {}
    try:
        max_steps = int(c.get("max_plan_steps", 6) or 6)
    except (TypeError, ValueError):
        max_steps = 6
    max_steps = max(1, min(12, max_steps))

    # Drop invalid/empty tasks.
    cleaned: list[dict] = []
    for s in plan:
        if not isinstance(s, dict):
            continue
        task = (s.get("task") or s.get("description") or "").strip()
        if not task:
            continue
        tools = s.get("tools") if isinstance(s.get("tools"), list) else []
        tools = [str(t).strip() for t in tools if str(t).strip()]
        cleaned.append(
            {
                **{k: v for k, v in s.items() if k not in ("task", "description", "tools", "step")},
                "task": task[:240],
                "tools": tools[:8],
            }
        )

    if not cleaned:
        return [], False, "no_valid_steps"

    # Deduplicate consecutive identical steps (same task + same tools).
    deduped: list[dict] = []
    prev_key: tuple[str, tuple[str, ...]] | None = None
    for s in cleaned:
        key = (str(s.get("task") or "").strip().lower(), tuple(str(t).strip() for t in (s.get("tools") or []) if str(t).strip()))
        if prev_key is not None and key == prev_key:
            continue
        prev_key = key
        deduped.append(s)

    # Ensure inspection before mutation: if any mutating tool appears and there is no read/grep/list step early, inject one.
    mut_tools = {"write_file", "apply_patch", "replace_in_file", "write_files_batch"}
    inspect_tools = {"read_file", "grep_code", "list_dir", "glob_files"}
    has_mut = any(any(t in mut_tools for t in (s.get("tools") or [])) for s in deduped)
    has_inspect_early = any(any(t in inspect_tools for t in (s.get("tools") or [])) for s in deduped[:2])
    if has_mut and not has_inspect_early:
        injected = {
            "step": 1,
            "task": "Inspect relevant files and current state before any mutation.",
            "tools": ["read_file", "grep_code", "list_dir"],
            "role": "analysis",
            "_pre_validation_injected": True,
            "_workspace_root_hint": (workspace_root or "")[:200],
        }
        deduped = [injected] + deduped

    # Cap steps.
    deduped = deduped[:max_steps]

    # Re-number steps.
    out: list[dict] = []
    for i, s in enumerate(deduped, start=1):
        d = dict(s)
        d["step"] = i
        out.append(d)

    return out, True, "ok"


def execute_plan_with_optional_graph(
    plan: list[dict],
    agent_run_fn: Any,
    goal_prefix: str = "",
    plan_depth: int = 0,
    *,
    step_governance: bool = False,
    default_max_retries: int = 1,
    cfg: dict | None = None,
    **agent_kwargs: Any,
) -> dict:
    """
    Like execute_plan, but when coordinator_graph_execution_enabled and len(plan) >= 2,
    run steps through the task graph (parallel-ready waves). Falls back to sequential
    execute_plan if the graph fails or is disabled.
    """
    import uuid

    try:
        import runtime_safety

        c = cfg if isinstance(cfg, dict) else runtime_safety.load_config()
    except Exception:
        c = cfg if isinstance(cfg, dict) else {}

    if not plan:
        return {"status": "no_plan", "steps_done": [], "summary": ""}

    # Behavior lock-in: graph execution is authoritative (no sequential fallback).
    if not bool(c.get("coordinator_graph_execution_enabled", False)):
        raise RuntimeError("graph_execution_disabled")

    defaults = {
        "context": "",
        "workspace_root": "",
        "allow_write": False,
        "allow_run": False,
        "conversation_history": [],
        "aspect_id": "morrigan",
        "show_thinking": False,
        "active_plan_id": "",
        "plan_approved": False,
    }
    defaults.update(agent_kwargs)
    defaults["plan_depth"] = plan_depth + 1

    dm = max(0, min(3, int(default_max_retries) if isinstance(default_max_retries, int) else 1))

    norm: list[dict] = []
    for s in plan:
        if not isinstance(s, dict):
            continue
        d = dict(s)
        sid = str(d.get("id") or "").strip()
        if not sid:
            sid = str(uuid.uuid4())[:8]
        d["id"] = sid
        norm.append(d)

    by_id: dict[str, dict[str, Any]] = {str(d["id"]): d for d in norm}

    def _step_goal_for_base(base: dict[str, Any]) -> str:
        task = base.get("task", "") or ""
        tools_hint = base.get("tools", [])
        if not isinstance(tools_hint, list):
            tools_hint = []
        role = base.get("role", "") or ""
        step_goal = str(task)
        if tools_hint:
            step_goal += f" (consider: {', '.join(str(t) for t in tools_hint[:3])})"
        if role and role in ROLE_TOOL_HINTS:
            step_goal += f" [{ROLE_TOOL_HINTS[role]}]"
        if goal_prefix:
            step_goal = f"{goal_prefix}\n\nStep {base.get('step', '?')}: {step_goal}"
        return step_goal

    def step_runner(sd: dict[str, Any]) -> dict[str, Any]:
        nid = str(sd.get("step") or "")
        base = by_id.get(nid)
        if not base:
            base = {
                "step": sd.get("step"),
                "task": sd.get("task", ""),
                "tools": sd.get("tools") if isinstance(sd.get("tools"), list) else [],
                "role": sd.get("role", ""),
            }
        task = base.get("task", "") or ""
        tools_hint = base.get("tools", [])
        if not isinstance(tools_hint, list):
            tools_hint = []
        role = base.get("role", "") or ""
        step_goal = _step_goal_for_base(base)

        if not step_governance:
            try:
                result = agent_run_fn(step_goal, **_filter_autonomous_kwargs(defaults))
                return {
                    "step": base.get("step"),
                    "task": task,
                    "result_status": result.get("status", ""),
                }
            except Exception as e:
                return {"step": base.get("step"), "task": task, "result_status": "error", "error": str(e)}

        exec_row = {
            "step": base.get("step"),
            "task": task,
            "tools": tools_hint,
            "role": role,
            "max_retries": base.get("max_retries", dm),
            "validation_hint": str(base.get("validation_hint") or "").strip(),
            "success_criteria": str(base.get("success_criteria") or "").strip(),
        }
        done_row, _last = run_governed_plan_step(
            exec_row,
            step_goal,
            agent_run_fn=agent_run_fn,
            agent_kwargs=defaults,
            default_max_retries=dm,
        )
        done_row["task"] = task
        return done_row

    from services.coordinator import run_with_plan_graph
    from services.otel_export import maybe_span

    with maybe_span(c, "plan_execution", steps=len(norm), graph_enabled="true"):
        try:
            gres = run_with_plan_graph(plan_steps=norm, step_runner=step_runner, cfg=c)
        except Exception as e:
            logger.warning("execute_plan_with_optional_graph: graph executor raised: %s", e)
            gres = {"ok": False, "error": str(e), "reason": "exception"}

    if not gres.get("ok"):
        # Hard-fail: do not fall back to sequential execution.
        raise RuntimeError(f"graph_execution_failed:{str(gres.get('reason') or gres.get('error') or 'unknown')[:240]}")

    raw: list[Any] = list(gres.get("results") or [])

    def _sort_key(row: Any) -> tuple[int, Any]:
        if not isinstance(row, dict):
            return (2, 0)
        st = row.get("step")
        try:
            return (0, int(st)) if st is not None else (1, 0)
        except (TypeError, ValueError):
            return (1, str(st))

    steps_done = sorted(raw, key=_sort_key)
    summary = "\n".join(
        f"{d.get('step')}. {d.get('task')}: {d.get('result_status', '')}"
        for d in steps_done
        if isinstance(d, dict)
    )
    out: dict[str, Any] = {"status": "plan_completed", "steps_done": steps_done, "summary": summary}
    if step_governance:
        out["all_steps_ok"] = all(isinstance(d, dict) and bool(d.get("governance_ok")) for d in steps_done)
    return out
