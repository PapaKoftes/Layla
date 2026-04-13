"""
Optional engineering pipeline: blocking clarifier, planner, forced critics, refiner overwrite,
governed execute_plan, mandatory validator (execute mode). See docs/STRUCTURED_ENGINEERING_PARTNER.md.
"""
from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar, Token
from typing import Any, Callable

logger = logging.getLogger("layla")

# When True, agent_loop skips legacy should_plan and skips re-entering execute pipeline (nested steps).
_engineering_planning_locked: ContextVar[bool] = ContextVar("engineering_planning_locked", default=False)


def engineering_planning_locked() -> bool:
    return bool(_engineering_planning_locked.get())


def lock_engineering_planning() -> Token:
    return _engineering_planning_locked.set(True)


def unlock_engineering_planning(token: Token) -> None:
    try:
        _engineering_planning_locked.reset(token)
    except Exception:
        pass


def _completion_text(out: dict) -> str:
    if not isinstance(out, dict):
        return ""
    ch0 = (out.get("choices") or [{}])[0]
    msg = (ch0.get("message") or {}) if isinstance(ch0, dict) else {}
    t = (msg.get("content") or "").strip()
    if t:
        return t
    return (ch0.get("text") or "").strip() if isinstance(ch0, dict) else ""


def _parse_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    text = text.strip()
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_json_array(text: str) -> list | None:
    if not text:
        return None
    try:
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return None
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def run_clarifier(
    goal: str,
    context: str,
    cfg: dict,
    clarification_reply: str = "",
) -> dict[str, Any]:
    """
    Returns {"status": "ok"} or {"status": "needs_input", "questions": [...]}.
    """
    try:
        from services.llm_gateway import run_completion
    except Exception as e:
        logger.warning("engineering_pipeline clarifier: no llm %s", e)
        return {"status": "ok"}

    g = (goal or "").strip()[:2000]
    c = (context or "").strip()[:4000]
    cr = (clarification_reply or "").strip()[:4000]
    block = f"Goal:\n{g}\n\nContext:\n{c}\n"
    if cr:
        block += f"\nOperator clarification (answers to prior questions):\n{cr}\n"
    prompt = (
        f"{block}\n"
        "You are a strict clarifier for an engineering agent. "
        "If the goal is underspecified for safe execution (missing target, constraints, acceptance, or workspace scope), "
        "you MUST ask questions — do NOT guess.\n"
        "Output ONLY a JSON object, no markdown:\n"
        'Either {"status":"ok"} if the goal is sufficiently specified,\n'
        'or {"status":"needs_input","questions":["question1","question2"]} with 1-5 concrete questions.\n'
        'If status is needs_input, questions must be non-empty strings.'
    )
    try:
        out = run_completion(prompt, max_tokens=400, temperature=0.1, stream=False)
        text = _completion_text(out if isinstance(out, dict) else {})
        obj = _parse_json_object(text) or {}
        st = str(obj.get("status") or "").strip().lower()
        if st == "needs_input":
            qs = obj.get("questions")
            if not isinstance(qs, list):
                qs = []
            questions = [str(q).strip() for q in qs if str(q).strip()]
            if questions:
                return {"status": "needs_input", "questions": questions}
        return {"status": "ok"}
    except Exception as e:
        logger.debug("run_clarifier failed: %s", e)
        return {"status": "ok"}


def run_critic_wrong(plan_json: str, goal: str, cfg: dict) -> list[str]:
    """Critic A: argue the plan is wrong."""
    try:
        from services.llm_gateway import run_completion
    except Exception:
        return ["Assume plan may be wrong; verify assumptions manually."]

    prompt = (
        f"Goal:\n{(goal or '')[:1200]}\n\nProposed plan (JSON):\n{plan_json[:6000]}\n\n"
        "You are Critic A. You MUST argue that this plan is WRONG or risky in at least one concrete way "
        "(incorrect assumptions, bad ordering, unsafe steps, wrong tech). "
        "You are NOT allowed to say the plan is fine or mostly good. "
        "Output ONLY JSON: {\"objections\": [\"...\", \"...\"] } with 2-5 non-empty objections."
    )
    try:
        out = run_completion(prompt, max_tokens=350, temperature=0.2, stream=False)
        text = _completion_text(out if isinstance(out, dict) else {})
        obj = _parse_json_object(text) or {}
        obs = obj.get("objections")
        if isinstance(obs, list):
            return [str(o).strip() for o in obs if str(o).strip()][:8]
    except Exception as e:
        logger.debug("critic_wrong failed: %s", e)
    return ["Plan may rely on unstated assumptions; validate each step against the repo."]


def run_critic_incomplete(plan_json: str, goal: str, cfg: dict) -> list[str]:
    """Critic B: argue the plan is incomplete."""
    try:
        from services.llm_gateway import run_completion
    except Exception:
        return ["Assume missing verification steps."]

    prompt = (
        f"Goal:\n{(goal or '')[:1200]}\n\nProposed plan (JSON):\n{plan_json[:6000]}\n\n"
        "You are Critic B. You MUST argue that this plan is INCOMPLETE "
        "(missing steps, tests, rollback, docs, edge cases, or acceptance criteria). "
        "You are NOT allowed to approve the plan or say it is sufficient. "
        "Output ONLY JSON: {\"objections\": [\"...\", \"...\"] } with 2-5 non-empty objections."
    )
    try:
        out = run_completion(prompt, max_tokens=350, temperature=0.2, stream=False)
        text = _completion_text(out if isinstance(out, dict) else {})
        obj = _parse_json_object(text) or {}
        obs = obj.get("objections")
        if isinstance(obs, list):
            return [str(o).strip() for o in obs if str(o).strip()][:8]
    except Exception as e:
        logger.debug("critic_incomplete failed: %s", e)
    return ["Plan may omit validation or failure handling; add explicit check steps."]


def run_refiner(
    plan: list[dict],
    objections_a: list[str],
    objections_b: list[str],
    goal: str,
    cfg: dict,
) -> list[dict]:
    """Return a single clean overwritten plan (list of step dicts)."""
    try:
        from services.llm_gateway import run_completion
    except Exception:
        return plan

    plan_json = json.dumps(plan, ensure_ascii=False)[:7000]
    oa = json.dumps(objections_a, ensure_ascii=False)[:2000]
    ob = json.dumps(objections_b, ensure_ascii=False)[:2000]
    prompt = (
        f"Goal:\n{(goal or '')[:1000]}\n\n"
        f"Current plan JSON:\n{plan_json}\n\n"
        f"Critic objections (plan wrong):\n{oa}\n\n"
        f"Critic objections (plan incomplete):\n{ob}\n\n"
        "Produce ONE revised plan as a JSON array ONLY. Each element: "
        '{"step": 1, "task": "short description", "tools": ["tool1"]}. '
        "3-8 steps. Do not include comments, notes, or prose outside the array. "
        "Overwrite the plan completely; merge fixes into the steps."
    )
    try:
        out = run_completion(prompt, max_tokens=500, temperature=0.15, stream=False)
        text = _completion_text(out if isinstance(out, dict) else {})
        arr = _parse_json_array(text)
        if arr:
            norm: list[dict] = []
            for i, row in enumerate(arr):
                if not isinstance(row, dict):
                    continue
                norm.append({
                    "step": int(row.get("step") or i + 1),
                    "task": str(row.get("task") or "").strip() or f"Step {i+1}",
                    "tools": [str(t).strip() for t in (row.get("tools") or []) if str(t).strip()],
                })
            if norm:
                return norm
    except Exception as e:
        logger.debug("run_refiner failed: %s", e)
    return plan


def run_validator(
    goal: str,
    plan_summary: str,
    steps_done: list[dict],
    all_steps_ok: bool,
    cfg: dict,
) -> dict[str, Any]:
    """
    Mandatory gate for execute mode. Returns {ok, failure_report?, retry_suggested?}.
    """
    try:
        from services.llm_gateway import run_completion
    except Exception:
        return {"ok": bool(all_steps_ok), "failure_report": "", "retry_suggested": False}

    sd = json.dumps(steps_done, default=str)[:6000]
    prompt = (
        f"Goal:\n{(goal or '')[:1200]}\n\n"
        f"Plan execution summary:\n{(plan_summary or '')[:2000]}\n\n"
        f"Step results (JSON):\n{sd}\n\n"
        f"Governance all_steps_ok flag: {all_steps_ok}\n\n"
        "You validate whether the engineering objective is adequately met. "
        "Output ONLY JSON: {\"ok\": true|false, \"failure_report\": \"...\", \"retry_suggested\": true|false}. "
        "If governance failed or results are empty where edits were required, ok should be false."
    )
    try:
        out = run_completion(prompt, max_tokens=300, temperature=0.1, stream=False)
        text = _completion_text(out if isinstance(out, dict) else {})
        obj = _parse_json_object(text) or {}
        ok = bool(obj.get("ok", all_steps_ok))
        return {
            "ok": ok,
            "failure_report": str(obj.get("failure_report") or "").strip(),
            "retry_suggested": bool(obj.get("retry_suggested", False)),
        }
    except Exception as e:
        logger.debug("run_validator failed: %s", e)
        return {"ok": bool(all_steps_ok), "failure_report": "validator_error", "retry_suggested": False}


def run_plan_light(
    goal: str,
    context: str,
    workspace_root: str,
    conversation_id: str,
    cfg: dict,
    clarification_reply: str = "",
    aspect_id: str = "morrigan",
) -> dict[str, Any]:
    """
    Clarifier + create_plan + persist layla_plan. Returns router-shaped dict or needs_input.
    """
    cl = run_clarifier(goal, context, cfg, clarification_reply=clarification_reply)
    if cl.get("status") == "needs_input":
        return {
            "status": "pipeline_needs_input",
            "pipeline_status": "needs_input",
            "questions": cl.get("questions") or [],
            "goal": goal,
            "conversation_id": conversation_id,
        }

    from services.planner import create_plan
    from services.engine_plans import normalize_planner_steps

    digest = ""
    wr = (workspace_root or "").strip()
    if wr:
        try:
            from services.plan_workspace_store import prior_plans_digest

            digest = prior_plans_digest(wr, limit=8)
        except Exception:
            digest = ""
    plan_steps = create_plan(
        goal,
        6,
        cfg,
        digest,
        conversation_id=conversation_id,
        aspect_id=aspect_id or "morrigan",
    )
    steps_norm = normalize_planner_steps(plan_steps)
    from layla.memory.db import create_layla_plan, get_layla_plan

    plan_row_id = create_layla_plan(
        goal,
        context=context,
        steps=steps_norm,
        workspace_root=workspace_root or "",
        conversation_id=conversation_id,
        status="draft",
    )
    prow = get_layla_plan(plan_row_id)
    if prow:
        try:
            from services.plan_workspace_store import mirror_sqlite_plan

            mirror_sqlite_plan(prow)
        except Exception:
            pass
    if wr and cfg.get("project_memory_persist_plan", True):
        try:
            from pathlib import Path

            from layla.tools.registry import inside_sandbox
            from services.project_memory import persist_plan_to_memory

            wrp = Path(wr).expanduser().resolve()
            if inside_sandbox(wrp):
                persist_plan_to_memory(wrp, goal, plan_steps)
        except Exception:
            pass
    return {
        "status": "plan_ready",
        "pipeline_status": "plan_ready",
        "plan": plan_steps,
        "plan_id": plan_row_id,
        "plan_steps": steps_norm,
        "goal": goal,
        "response": "",
        "ux_states": ["plan_ready", "engineering_pipeline_plan"],
    }


def run_execute_pipeline(
    *,
    goal: str,
    context: str,
    workspace_root: str,
    allow_write: bool,
    allow_run: bool,
    conversation_history: list,
    aspect_id: str,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue: Any,
    research_mode: bool,
    plan_depth: int,
    persona_focus: str,
    conversation_id: str,
    cognition_workspace_roots: list[str] | None,
    client_abort_event: Any,
    background_progress_callback: Any,
    clarification_reply: str,
    cfg: dict,
    agent_run_fn: Callable[..., dict],
    memory_influenced: list,
    active_aspect: dict,
) -> dict[str, Any]:
    """
    Full execute mode: clarify → plan → critics → refiner → execute_plan → validator.
    Returns a completed state dict (caller merges aspect fields).
    """
    import time

    from services.planner import create_plan, execute_plan, normalize_plan_steps_tools
    from services.resource_manager import classify_load

    t0 = time.perf_counter()
    cl = run_clarifier(goal, context, cfg, clarification_reply=clarification_reply)
    if cl.get("status") == "needs_input":
        qs = cl.get("questions") or []
        _qr = "\n".join(f"- {q}" for q in qs) if qs else "More information needed."
        try:
            from services.telemetry import log_event
            import runtime_safety

            log_event(
                "engineering_pipeline_execute",
                "deep",
                None,
                (time.perf_counter() - t0) * 1000,
                True,
                str(runtime_safety.load_config().get("performance_mode") or ""),
            )
        except Exception:
            pass
        return {
            "status": "pipeline_needs_input",
            "pipeline_status": "needs_input",
            "questions": qs,
            "steps": [],
            "response": _qr,
            "reasoning_mode": "deep",
            "goal": goal,
            "conversation_id": conversation_id,
            "ux_states": ["pipeline_needs_input"],
            "memory_influenced": memory_influenced,
            "aspect": active_aspect.get("id", "layla"),
            "aspect_name": active_aspect.get("name", "Layla"),
            "refused": False,
            "refusal_reason": "",
            "load": classify_load(),
        }

    digest = ""
    wr = (workspace_root or "").strip()
    if wr:
        try:
            from services.plan_workspace_store import prior_plans_digest

            digest = prior_plans_digest(wr, limit=8)
        except Exception:
            digest = ""

    plan = create_plan(
        goal,
        max_steps=6,
        cfg=cfg,
        prior_plans_digest=digest,
        conversation_id=conversation_id,
        aspect_id=aspect_id or "morrigan",
    )
    if not plan:
        return {
            "status": "pipeline_failed",
            "pipeline_status": "planner_empty",
            "response": "Engineering pipeline could not produce a plan.",
            "steps": [],
            "reasoning_mode": "deep",
            "aspect": active_aspect.get("id", "layla"),
            "aspect_name": active_aspect.get("name", "Layla"),
            "refused": False,
            "refusal_reason": "",
            "ux_states": ["pipeline_failed"],
            "memory_influenced": memory_influenced,
            "load": classify_load(),
        }

    if bool(cfg.get("in_loop_plan_governance_enabled")) and bool(
        cfg.get("plan_governance_require_nonempty_step_tools")
    ):
        normalize_plan_steps_tools(plan, cfg)

    plan_json = json.dumps(plan, ensure_ascii=False)
    obj_a = run_critic_wrong(plan_json, goal, cfg)
    obj_b = run_critic_incomplete(plan_json, goal, cfg)
    refined = run_refiner(plan, obj_a, obj_b, goal, cfg)

    from layla.memory.db import create_layla_plan, get_layla_plan, update_layla_plan
    from services.engine_plans import normalize_planner_steps

    steps_norm = normalize_planner_steps(refined)
    strict = bool(cfg.get("planning_strict_mode"))
    approved = (allow_write or allow_run) and not strict
    if strict:
        st = "draft"
    else:
        st = "approved" if (allow_write or allow_run) else "draft"
    plan_row_id = create_layla_plan(
        goal,
        context=context,
        steps=steps_norm,
        workspace_root=workspace_root or "",
        conversation_id=conversation_id,
        status=st,
    )
    prow = get_layla_plan(plan_row_id)
    if prow:
        try:
            from services.plan_workspace_store import mirror_sqlite_plan

            mirror_sqlite_plan(prow)
        except Exception:
            pass

    plan_approved = st == "approved"
    if strict and (allow_write or allow_run) and st == "draft":
        plan_approved = False

    try:
        _dm = int(cfg.get("in_loop_plan_default_max_retries", 1) or 1)
    except (TypeError, ValueError):
        _dm = 1
    _dm = max(0, min(3, _dm))

    plan_context = context or ""
    _exec_common = dict(
        context=plan_context,
        workspace_root=workspace_root,
        allow_write=allow_write,
        allow_run=allow_run,
        conversation_history=conversation_history or [],
        aspect_id=aspect_id or "morrigan",
        show_thinking=show_thinking,
        stream_final=False,
        ux_state_queue=ux_state_queue,
        research_mode=research_mode,
        conversation_id=conversation_id,
        skip_engineering_pipeline=True,
        persona_focus=persona_focus,
        cognition_workspace_roots=cognition_workspace_roots,
        client_abort_event=client_abort_event,
        background_progress_callback=background_progress_callback,
        active_plan_id=plan_row_id,
        plan_approved=plan_approved,
    )

    tok = lock_engineering_planning()
    try:
        plan_result = execute_plan(
            refined,
            agent_run_fn,
            goal_prefix=goal[:100],
            plan_depth=plan_depth,
            step_governance=True,
            default_max_retries=_dm,
            **_exec_common,
        )
    finally:
        unlock_engineering_planning(tok)

    all_ok = bool(plan_result.get("all_steps_ok")) if isinstance(plan_result, dict) else False
    summary = str(plan_result.get("summary") or "")
    steps_done = plan_result.get("steps_done") or []

    vmax = int(cfg.get("engineering_pipeline_validator_max_retries", 1) or 1)
    vmax = max(0, min(2, vmax))
    val = run_validator(goal, summary, steps_done, all_ok, cfg)
    attempts = 0
    while not val.get("ok") and val.get("retry_suggested") and attempts < vmax:
        attempts += 1
        tok = lock_engineering_planning()
        try:
            plan_result = execute_plan(
                refined,
                agent_run_fn,
                goal_prefix=goal[:100] + " (retry after validation)",
                plan_depth=plan_depth,
                step_governance=True,
                default_max_retries=_dm,
                **_exec_common,
            )
        finally:
            unlock_engineering_planning(tok)
        all_ok = bool(plan_result.get("all_steps_ok")) if isinstance(plan_result, dict) else False
        summary = str(plan_result.get("summary") or "")
        steps_done = plan_result.get("steps_done") or []
        val = run_validator(goal, summary, steps_done, all_ok, cfg)

    if prow:
        try:
            update_layla_plan(plan_row_id, status="done" if val.get("ok") and all_ok else "blocked")
            np = get_layla_plan(plan_row_id)
            if np:
                mirror_sqlite_plan(np)
        except Exception:
            pass

    reply = summary
    if not val.get("ok"):
        fr = val.get("failure_report") or "Validation did not pass."
        reply = f"{summary}\n\n[Validator]: {fr}"

    try:
        from services.telemetry import log_event
        import runtime_safety

        log_event(
            "engineering_pipeline_execute",
            "deep",
            None,
            (time.perf_counter() - t0) * 1000,
            bool(val.get("ok") and all_ok),
            str(runtime_safety.load_config().get("performance_mode") or ""),
        )
    except Exception:
        pass

    out = {
        "status": "pipeline_completed" if val.get("ok") else "pipeline_validator_failed",
        "pipeline_status": "completed" if val.get("ok") else "validator_failed",
        "steps": [{"action": "reason", "result": reply, "pipeline_steps_done": steps_done}],
        "reply": reply,
        "response": reply,
        "reasoning_mode": "deep",
        "aspect": active_aspect.get("id", "layla"),
        "aspect_name": active_aspect.get("name", "Layla"),
        "refused": False,
        "refusal_reason": "",
        "ux_states": ["engineering_pipeline_execute", "pipeline_completed" if val.get("ok") else "pipeline_validator_failed"],
        "memory_influenced": memory_influenced,
        "load": classify_load(),
        "all_steps_ok": all_ok,
        "pipeline_plan_id": plan_row_id,
        "validator_ok": bool(val.get("ok")),
        "failure_report": val.get("failure_report") or "",
    }
    return out
