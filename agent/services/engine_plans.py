"""
Normalize planner output <-> durable layla_plans step schema and executor format.

Also hosts **run_plan_iteration**: file-backed plan brain (analyze vs execute step)
used by background workers instead of a raw autonomous_run when `file_plan_id` is set.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("layla")


def normalize_planner_steps(steps: list[dict] | None) -> list[dict[str, Any]]:
    """Map create_plan() rows to {id, type, description, status, tools?}."""
    out: list[dict[str, Any]] = []
    if not steps:
        return out
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        desc = (s.get("task") or s.get("description") or "").strip()
        if not desc:
            continue
        tools = s.get("tools") or []
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]
        out.append({
            "id": int(s.get("step", i + 1)),
            "type": (s.get("role") or s.get("type") or "task")[:64],
            "description": desc[:2000],
            "status": (s.get("status") or "pending")[:32],
            "tools": [str(t)[:80] for t in tools[:12] if t],
        })
    return out


def steps_for_planner_execution(steps: list[dict]) -> list[dict[str, Any]]:
    """Convert stored schema back to services.planner.execute_plan format."""
    exec_steps: list[dict[str, Any]] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        tid = s.get("id")
        try:
            mr = int(s.get("max_retries", 1) or 1)
        except (TypeError, ValueError):
            mr = 1
        mr = max(0, min(3, mr))
        exec_steps.append({
            "step": int(tid) if tid is not None else len(exec_steps) + 1,
            "task": (s.get("description") or "")[:2000],
            "tools": s.get("tools") if isinstance(s.get("tools"), list) else [],
            "role": (s.get("type") or "")[:64],
            "max_retries": mr,
        })
    return exec_steps


def mirror_plan_to_project_memory_patch(plan: dict) -> dict[str, Any]:
    """Small patch for project_memory.plans list + active plan summary."""
    pid = plan.get("id") or ""
    entry = {
        "plan_id": pid,
        "status": plan.get("status"),
        "goal": (plan.get("goal") or "")[:500],
        "updated_at": plan.get("updated_at"),
        "step_count": len(plan.get("steps") or []),
    }
    return {
        "plan": {
            "goal": (plan.get("goal") or "")[:2000],
            "steps": plan.get("steps") or [],
            "current_step_index": 0,
            "status": plan.get("status") or "",
        },
        "plans": [entry],
    }


# ─── File-plan iteration (autonomous_run wrapper, no router import) ─────────


def _summarize_result(resp: dict[str, Any]) -> str:
    txt = str(resp.get("response") or "")
    if len(txt) > 400:
        return txt[:400] + "..."
    return txt


def _extract_findings(resp: dict[str, Any]) -> dict[str, Any]:
    st = resp.get("state") if isinstance(resp.get("state"), dict) else {}
    steps = st.get("steps") or []
    if not isinstance(steps, list):
        steps = []
    return {"step_count": len(steps)}


def _is_low_quality(resp: dict[str, Any]) -> bool:
    txt = (resp.get("response") or "").strip()
    return (not txt) or len(txt) < 20


def _autonomous_kwargs_from_payload(payload: dict[str, Any], goal: str) -> dict[str, Any]:
    """Map background / caller payload to autonomous_run keyword args."""
    from services.resource_manager import PRIORITY_AGENT

    pri = payload.get("_schedule_priority")
    try:
        p_int = int(pri) if pri is not None else PRIORITY_AGENT
    except (TypeError, ValueError):
        p_int = PRIORITY_AGENT
    return {
        "goal": goal,
        "context": str(payload.get("context") or ""),
        "workspace_root": str(payload.get("workspace_root") or ""),
        "allow_write": bool(payload.get("allow_write")),
        "allow_run": bool(payload.get("allow_run")),
        "conversation_history": list(payload.get("conversation_history") or []),
        "aspect_id": str(payload.get("aspect_id") or "morrigan"),
        "show_thinking": bool(payload.get("show_thinking", False)),
        "stream_final": False,
        "ux_state_queue": payload.get("ux_state_queue"),
        "priority": p_int,
        "persona_focus": str(payload.get("persona_focus") or "").strip(),
        "conversation_id": str(payload.get("conversation_id") or "").strip(),
        "cognition_workspace_roots": payload.get("cognition_workspace_roots"),
        "client_abort_event": payload.get("client_abort_event"),
        "background_progress_callback": payload.get("background_progress_callback"),
        "active_plan_id": str(payload.get("active_plan_id") or ""),
        "plan_approved": bool(payload.get("plan_approved")),
        "fabrication_assist_runner_request": str(payload.get("fabrication_assist_runner_request") or "").strip(),
        "skip_engineering_pipeline": bool(payload.get("skip_engineering_pipeline")),
        "engineering_pipeline_mode": (
            _epm
            if (_epm := str(payload.get("engineering_pipeline_mode") or "chat").strip().lower())
            in ("chat", "plan", "execute")
            else "chat"
        ),
        "clarification_reply": str(payload.get("clarification_reply") or ""),
    }


def _call_autonomous(goal: str, payload: dict[str, Any]) -> dict[str, Any]:
    from agent_loop import autonomous_run
    from services.tool_allowlist_context import (
        clear_plan_step_tool_allowlist,
        set_plan_step_tool_allowlist,
    )

    raw_al = payload.get("_plan_step_tool_allowlist")
    if isinstance(raw_al, (list, tuple, set)) and len(raw_al) > 0:
        names = frozenset(str(x).strip() for x in raw_al if str(x).strip())
        set_plan_step_tool_allowlist(names if names else None)
    else:
        clear_plan_step_tool_allowlist()
    try:
        kw = _autonomous_kwargs_from_payload(payload, goal)
        return autonomous_run(**kw)
    finally:
        clear_plan_step_tool_allowlist()


def _run_with_refinement(goal: str, payload: dict[str, Any]) -> dict[str, Any]:
    r1 = _call_autonomous(goal, payload)
    if _is_low_quality(r1):
        improve = f"Improve this answer:\n{r1.get('response', '')}\nBe precise and concise."
        r2 = _call_autonomous(improve, payload)
        return r2
    return r1


def _build_step_prompt(plan: Any, step: Any) -> str:
    if getattr(step, "tools", None):
        tools_line = (
            "ONLY USE THESE TOOLS (server rejects any other tool name when this list is non-empty): "
            + ", ".join(step.tools)
            + "\n"
        )
    else:
        tools_line = (
            "TOOLS: any safe tools (respect allow_write/allow_run); "
            "no per-step allowlist unless step lists tools[]\n"
        )
    return (
        f"GOAL: {plan.goal}\n"
        f"MEMORY: {plan.memory_summary}\n"
        f"STEP: {step.title} — {step.description}\n"
        f"{tools_line}"
        "RULES:\n"
        "- Be concise.\n"
        "- Follow the step exactly.\n"
        "- Return a clear result summary after any tool use.\n"
    )


def _update_memory_after_iteration(workspace_root: str, resp: dict[str, Any]) -> None:
    try:
        from services import project_memory as pm

        mem = pm.load_memory(workspace_root)
        mem["last_iteration"] = _summarize_result(resp)
        sig = mem.setdefault("signals", {})
        if isinstance(sig, dict):
            sig["last_step_count"] = _extract_findings(resp)["step_count"]
            st = resp.get("state") if isinstance(resp.get("state"), dict) else {}
            raw = st.get("steps") or []
            actions: list[str] = []
            if isinstance(raw, list):
                for e in raw:
                    if isinstance(e, dict) and e.get("action"):
                        actions.append(str(e.get("action")))
            if actions:
                sig["last_tool_actions"] = actions[-20:]
        pm.save_memory(workspace_root, mem)
    except Exception as e:
        logger.debug("_update_memory_after_iteration: %s", e)


def _append_aspect_step_note(workspace_root: str, aspect_id: str, line: str) -> None:
    try:
        from services import project_memory as pm

        mem = pm.load_memory(workspace_root)
        aspects = mem.setdefault("aspects", {})
        if not isinstance(aspects, dict):
            return
        aid = (aspect_id or "morrigan").strip().lower() or "morrigan"
        block = aspects.setdefault(aid, {"notes": [], "focus": ""})
        if not isinstance(block, dict):
            return
        notes = block.setdefault("notes", [])
        if not isinstance(notes, list):
            notes = []
            block["notes"] = notes
        notes.append(line[:500])
        if len(notes) > 200:
            block["notes"] = notes[-200:]
        pm.save_memory(workspace_root, mem)
    except Exception as e:
        logger.debug("_append_aspect_step_note: %s", e)


def _planning_first_prompt(goal: str, context: str, memory_summary: str) -> str:
    return (
        "You are Layla (planning-first).\n\n"
        f"GOAL:\n{goal}\n\n"
        f"CONTEXT (brief):\n{context}\n\n"
        f"MEMORY SUMMARY:\n{memory_summary}\n\n"
        "Produce a concise plan with 3–7 steps.\n"
        "Each step:\n"
        "- title (short)\n"
        "- description (1–2 lines)\n"
        "- type (analysis/refactor/edit/test/build/cad/research)\n"
        "- tools (if known, else empty)\n\n"
        "Rules:\n"
        "- Prefer minimal steps\n"
        "- Order by dependencies\n"
        "- No execution, planning only\n"
        "Return a JSON array of objects with keys title, description, type, tools (array of strings).\n"
    )


def generate_or_refine_plan(plan: Any, workspace_root: str, payload: dict[str, Any]) -> dict[str, Any]:
    from services import project_memory as pm
    from services.plan_service import save_plan, touch_updated

    mem = pm.load_memory(workspace_root)
    plan.memory_summary = pm.summarize_memory(mem)
    prompt = _planning_first_prompt(plan.goal, plan.context, plan.memory_summary)
    resp = _run_with_refinement(prompt, payload)
    snippet = (resp.get("response") or "")[:8000]
    if snippet.strip():
        plan.notes.append(snippet)
        if len(plan.notes) > 40:
            plan.notes = plan.notes[-40:]
    touch_updated(plan)
    save_plan(workspace_root, plan)
    out = dict(resp)
    out["ok"] = True
    out["mode"] = "plan_refine"
    return out


def execute_next_file_plan_step(plan: Any, workspace_root: str, payload: dict[str, Any]) -> dict[str, Any]:
    from services import project_memory as pm
    from services.plan_execution_prompts import file_plan_retry_suffix
    from services.plan_service import save_plan, set_step_status, touch_updated
    from services.planner import run_governed_plan_step

    plan.memory_summary = pm.summarize_memory(pm.load_memory(workspace_root))
    step = plan.next_ready_step()
    if not step:
        plan.status = "done"
        touch_updated(plan)
        save_plan(workspace_root, plan)
        try:
            from services.plan_workspace_store import append_plan_history

            append_plan_history(
                workspace_root,
                {
                    "plan_id": plan.id,
                    "source": "file",
                    "outcome": "done",
                    "goal_preview": (plan.goal or "")[:300],
                },
            )
        except Exception:
            pass
        return {"ok": True, "status": "done", "response": "All plan steps complete.", "steps": []}

    if step.approval_required and not bool(plan.allow_run):
        return {
            "ok": True,
            "mode": "waiting_for_approval",
            "step_id": step.id,
            "response": "Step requires allow_run on the plan (or enable allow_run for this background job).",
            "steps": [],
        }

    set_step_status(plan, step.id, "running")
    touch_updated(plan)
    save_plan(workspace_root, plan)

    prompt = _build_step_prompt(plan, step)
    step_tool_names = [
        str(x).strip() for x in (getattr(step, "tools", None) or []) if str(x).strip()
    ]
    exec_payload = {**payload, "active_plan_id": plan.id, "plan_approved": True}
    exec_payload["_plan_step_tool_allowlist"] = step_tool_names if step_tool_names else None

    # Fabrication Assist runner request: stub by default; subprocess only when explicitly enabled in config.
    fa_req = ""
    try:
        raw_in = getattr(step, "inputs", None) or {}
        if isinstance(raw_in, dict):
            fa_req = str(raw_in.get("fabrication_assist_runner") or "").strip().lower()
    except Exception:
        fa_req = ""
    if fa_req and fa_req not in ("stub", "subprocess"):
        fa_req = ""
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}
    _fa_cfg = cfg.get("fabrication_assist") if isinstance(cfg, dict) else {}
    if not isinstance(_fa_cfg, dict):
        _fa_cfg = {}
    allow_subprocess = bool(_fa_cfg.get("enable_subprocess"))
    if fa_req == "subprocess" and not allow_subprocess:
        # Hard block: step explicitly asked for subprocess but operator hasn't enabled it.
        set_step_status(plan, step.id, "blocked")
        plan.status = "failed"
        touch_updated(plan)
        save_plan(workspace_root, plan)
        return {
            "ok": True,
            "mode": "blocked",
            "plan_status": plan.status,
            "step_status": "blocked",
            "step_id": step.id,
            "response": "Fabrication Assist subprocess runner requested by plan step but disabled by config. Set fabrication_assist.enable_subprocess=true to allow.",
            "steps": [],
        }
    # Pass request through payload so agent_loop can pin tool args deterministically (never LLM-decided).
    exec_payload["fabrication_assist_runner_request"] = fa_req or "stub"

    max_retries = int(getattr(step, "max_retries", 1) or 0)

    def _result_fn(g: str) -> dict[str, Any]:
        return _run_with_refinement(g, exec_payload)

    step_row = {
        "step": step.id,
        "task": f"{step.title}: {step.description}".strip()[:2000],
        "tools": step_tool_names,
        "role": str(step.type or "analysis"),
        "max_retries": max_retries,
        "_tools_auto_filled": bool(getattr(step, "tools_auto_filled", False)),
        "validation_hint": str(getattr(step, "validation_hint", None) or "").strip(),
        "success_criteria": str(getattr(step, "success_criteria", None) or "").strip(),
    }
    done_row, last_resp = run_governed_plan_step(
        step_row,
        prompt,
        agent_result_fn=_result_fn,
        default_max_retries=max_retries,
        retry_suffix_fn=file_plan_retry_suffix,
    )
    success = bool(done_row.get("governance_ok"))
    attempt = max(0, int(done_row.get("attempts", 1)) - 1)
    step.outputs = {
        "response": last_resp.get("response", ""),
        "state": last_resp.get("state", {}),
        "validation_ok": success,
        "validation_error": done_row.get("validation_error", ""),
        "low_confidence": done_row.get("low_confidence"),
        "refused": bool(done_row.get("refused")),
        "attempt": done_row.get("attempts", 1),
        "governance_row": done_row,
    }
    if attempt > 0:
        step.retries = attempt
    touch_updated(plan)
    save_plan(workspace_root, plan)

    if success:
        set_step_status(plan, step.id, "done")
        plan.status = "executing"
        touch_updated(plan)
        save_plan(workspace_root, plan)
        _update_memory_after_iteration(workspace_root, last_resp)
        _append_aspect_step_note(
            workspace_root,
            str(payload.get("aspect_id") or "morrigan"),
            f"Completed step {step.title!r} ({step.id})",
        )
    else:
        set_step_status(plan, step.id, "blocked")
        plan.status = "failed"
        touch_updated(plan)
        save_plan(workspace_root, plan)
        _update_memory_after_iteration(workspace_root, last_resp)
        try:
            from services.plan_workspace_store import append_plan_history

            append_plan_history(
                workspace_root,
                {
                    "plan_id": plan.id,
                    "source": "file",
                    "outcome": "blocked",
                    "goal_preview": (plan.goal or "")[:300],
                    "step_id": step.id,
                },
            )
        except Exception:
            pass

    out = dict(last_resp)
    out["ok"] = True
    out["step_id"] = step.id
    out["step_success"] = success
    out["refused"] = bool(last_resp.get("refused"))
    if not success:
        out["plan_status"] = plan.status
        out["step_status"] = step.status
    return out


def run_plan_iteration(
    workspace_root: str,
    plan_id: str,
    *,
    planning_strict_mode: bool,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """One purposeful iteration: refine plan (draft / strict-unapproved) or execute next approved step."""
    from services.plan_service import load_plan

    wr = (workspace_root or "").strip()
    if not wr:
        return {"ok": False, "error": "workspace_root required", "response": "", "steps": []}

    plan = load_plan(wr, plan_id)
    if plan is None:
        return {"ok": False, "error": "plan_not_found", "response": "", "steps": []}

    from services import project_memory as pm

    mem = pm.load_memory(wr)
    plan.memory_summary = pm.summarize_memory(mem)

    if plan.status in ("done", "blocked", "failed", "paused"):
        return {"ok": True, "status": plan.status, "response": "", "steps": []}

    if planning_strict_mode and plan.status not in ("approved", "executing"):
        p = {**payload, "allow_run": False, "allow_write": False}
        r = generate_or_refine_plan(plan, wr, p)
        r["mode"] = "analysis_only"
        return r

    if plan.status == "draft":
        return generate_or_refine_plan(plan, wr, payload)

    if plan.status in ("approved", "executing"):
        return execute_next_file_plan_step(plan, wr, payload)

    return {"ok": True, "status": plan.status, "response": "", "steps": []}


def run_file_plan_background_loop(
    task_id: str,
    payload: dict[str, Any],
    client_abort: Any,
    progress_cb: Any,
    max_iter: int,
    delay_s: float,
) -> dict[str, Any]:
    """Continuous: run_plan_iteration until done, error, or cancel."""
    import runtime_safety

    cfg = runtime_safety.load_config()
    strict = bool(cfg.get("planning_strict_mode"))
    ws = str(payload.get("workspace_root") or "").strip()
    pid = str(payload.get("file_plan_id") or "").strip()
    aggregate: list[Any] = []
    result: dict[str, Any] = {"status": "finished", "response": "", "steps": []}
    completed = 0

    conv_hist = list(payload.get("conversation_history") or [])
    started_at = time.time()

    for i in range(max_iter):
        if client_abort is not None and getattr(client_abort, "is_set", lambda: False)():
            result = {
                "status": "client_abort",
                "response": "cancelled",
                "steps": aggregate[-300:],
            }
            break
        if progress_cb:
            progress_cb(
                {
                    "type": "progress",
                    "phase": "file_plan_engine",
                    "task_id": task_id,
                    "iteration": i,
                    "max_iterations": max_iter,
                    "message": f"plan iteration {i + 1}/{max_iter}",
                }
            )

        p_wr = bool(payload.get("allow_write"))
        p_run = bool(payload.get("allow_run"))
        if strict:
            ap_sql = str(payload.get("active_plan_id") or "").strip()
            if not ap_sql or not payload.get("plan_approved"):
                p_wr = False
                p_run = False

        iter_payload = {
            **payload,
            "allow_write": p_wr,
            "allow_run": p_run,
            "conversation_history": conv_hist,
            "client_abort_event": client_abort,
            "background_progress_callback": progress_cb,
        }

        r = run_plan_iteration(ws, pid, planning_strict_mode=strict, payload=iter_payload)
        completed += 1
        aggregate.append({"iteration": i, "result": r})
        if len(aggregate) > 400:
            aggregate = aggregate[-400:]

        st = r.get("status") or r.get("mode")
        if r.get("ok") is False:
            result = {
                "status": "error",
                "response": r.get("error", "iteration_failed"),
                "steps": aggregate[-300:],
            }
            break
        if st == "done":
            result = {
                "status": "finished",
                "response": r.get("response") or "plan_done",
                "steps": aggregate[-300:],
            }
            try:
                _write_plan_completion_report(
                    workspace_root=ws,
                    file_plan_id=pid,
                    result=result,
                    started_at=started_at,
                )
            except Exception:
                pass
            break
        if st in ("blocked", "failed", "paused"):
            result = {"status": st, "response": r.get("response", ""), "steps": aggregate[-300:]}
            break

        if i < max_iter - 1 and delay_s > 0:
            time.sleep(delay_s)

    result = dict(result)
    result["continuous_iterations"] = completed
    result["file_plan_id"] = pid
    return result


def _write_plan_completion_report(*, workspace_root: str, file_plan_id: str, result: dict[str, Any], started_at: float) -> None:
    from pathlib import Path

    from layla.time_utils import utcnow
    from services.plan_service import load_plan

    wr = Path(str(workspace_root)).expanduser().resolve()
    pid = (file_plan_id or "").strip()
    if not pid:
        return
    plan = load_plan(str(wr), pid)
    if plan is None:
        return
    dur_s = max(0, int(time.time() - float(started_at or time.time())))
    ts = utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = wr / ".layla" / "plan_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pid}_{ts}.md"

    # Best-effort: summarize steps without LLM.
    steps = getattr(plan, "steps", []) or []
    lines: list[str] = []
    lines.append(f"# Plan report — {pid}")
    lines.append("")
    lines.append(f"**Status:** {getattr(plan, 'status', '')}")
    lines.append(f"**Goal:** {getattr(plan, 'goal', '')}")
    lines.append(f"**Completed at:** {utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append(f"**Duration:** {dur_s}s")
    lines.append("")
    lines.append("## Steps")
    for i, st in enumerate(steps[:200], start=1):
        try:
            title = (getattr(st, "title", "") or getattr(st, "name", "") or "").strip()
            status = (getattr(st, "status", "") or "").strip()
            lines.append(f"- {i}. [{status or '—'}] {title or '(step)'}")
        except Exception:
            continue
    lines.append("")
    lines.append("## Outcome")
    lines.append(str((result or {}).get("response") or "done"))
    lines.append("")

    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
