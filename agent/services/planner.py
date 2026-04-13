"""
Lightweight planning engine: break complex goals into executable steps.
Uses LLM to produce a structured plan (3–6 steps); each step has task + suggested tools.
Supports agent roles: planner, executor, researcher, debugger, memory_curator.
"""
import json
import re
from types import SimpleNamespace
from typing import Any

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
        if top:
            return f"Higher reliability (from past outcomes): {', '.join(top)}"
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


def build_planning_bias_prompt(conversation_id: str, aspect_id: str, cfg: dict | None) -> str:
    """Prior-turn evaluation + recent tool failures + persona + toolchain hint for create_plan."""
    if cfg is not None and not cfg.get("planning_outcome_bias_enabled", True):
        return ""
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
        bias_block = build_planning_bias_prompt(conversation_id or "", aspect_id or "", cfg)
        prompt = (
            f"Given this goal:\n\n{goal[:800]}\n\n"
            f"{extra_ctx}"
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

    last: dict[str, Any] = {}
    success = False
    attempt = 0
    verr = ""
    refused = False
    lc = False
    try:
        for attempt in range(max_attempts):
            use_goal = step_goal
            if attempt > 0:
                use_goal = step_goal + retry_suffix_fn(attempt, mr)
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

    summary = "\n".join(f"{d.get('step')}. {d.get('task')}: {d.get('result_status', '')}" for d in steps_done)
    out: dict[str, Any] = {"status": "plan_completed", "steps_done": steps_done, "summary": summary}
    if step_governance:
        out["all_steps_ok"] = all(d.get("governance_ok") for d in steps_done)
    return out
