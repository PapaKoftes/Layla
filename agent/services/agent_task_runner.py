"""Background agent tasks: queue, threaded/subprocess workers, shared task store."""
import json
import logging
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi.responses import JSONResponse

from services.resource_manager import PRIORITY_AGENT, PRIORITY_BACKGROUND, PRIORITY_CHAT
from shared_state import get_conv_history

logger = logging.getLogger("layla")

_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()


def _build_reasoning_tree_summary(state: dict) -> dict:
    """Summary-only reasoning tree; no chain-of-thought text."""
    st = state or {}
    steps = st.get("steps") or []
    nodes: list[dict] = []
    for idx, step in enumerate(steps):
        action = str(step.get("action", "")).strip()
        raw = step.get("result")
        if isinstance(raw, dict):
            outcome = str(raw.get("message") or raw.get("error") or raw.get("ok") or "completed")
        else:
            outcome = str(raw or "")
        nodes.append(
            {
                "id": f"step_{idx + 1}",
                "phase": "tool" if action and action != "reason" else "reasoning",
                "action": action or "reason",
                "outcome_summary": outcome[:200],
            }
        )
    return {
        "mode": "summary_only",
        "goal": str(st.get("original_goal") or st.get("goal") or "")[:300],
        "status": str(st.get("status") or ""),
        "reasoning_mode": str(st.get("reasoning_mode") or ""),
        "ux_states": [str(x) for x in (st.get("ux_states") or [])[:20]],
        "nodes": nodes[:30],
        "final_summary": (str(steps[-1].get("result"))[:280] if steps else ""),
    }


def _parse_schedule_priority(raw, default: int) -> int:
    """Map API priority to resource_manager tier: 0=chat, 1=agent, 2=background."""
    if raw is None:
        return default
    if isinstance(raw, int) and not isinstance(raw, bool):
        return max(PRIORITY_CHAT, min(PRIORITY_BACKGROUND, int(raw)))
    s = str(raw).strip().lower()
    if s in ("chat", "interactive"):
        return PRIORITY_CHAT
    if s in ("agent", "worker", "tiny"):
        return PRIORITY_AGENT
    if s in ("background", "bg", "async"):
        return PRIORITY_BACKGROUND
    try:
        n = int(s, 10)
        return max(PRIORITY_CHAT, min(PRIORITY_BACKGROUND, n))
    except ValueError:
        return default


def _compute_background_job_sandbox(cfg: dict, workspace_root: str) -> tuple[str | None, str]:
    """Returns (error_message_or_none, sandbox_root_str for worker)."""
    from layla.tools.registry import inside_sandbox

    base = Path(cfg.get("sandbox_root", str(Path.home()))).expanduser().resolve()
    force = bool(cfg.get("background_worker_force_sandbox_only"))
    ws = (workspace_root or "").strip()
    if ws and force:
        wp = Path(ws).expanduser().resolve()
        if not inside_sandbox(wp):
            return (
                "workspace_root is outside configured sandbox (enable only paths under sandbox_root, "
                "or set background_worker_force_sandbox_only to false)",
                "",
            )
    return None, str(base)


def _progress_events_cap(cfg: dict) -> int:
    try:
        return max(10, int(cfg.get("background_progress_max_events", 200) or 200))
    except (TypeError, ValueError):
        return 200


def _parse_stored_progress_events(raw: object) -> list[dict]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            pe = json.loads(raw)
            if isinstance(pe, list):
                return [x for x in pe if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return []


def _append_progress_event(task_id: str, event: dict) -> None:
    """Thread-safe append for background task progress; persists progress_json to SQLite."""
    import runtime_safety

    cfg = runtime_safety.load_config()
    max_ev = _progress_events_cap(cfg)
    ev = {k: v for k, v in event.items() if k != "type"}
    if not ev:
        return
    ev.setdefault("t", time.time())
    pj = "[]"
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        if not t:
            return
        pe = t.get("progress_events")
        if not isinstance(pe, list):
            pe = []
        pe.append(ev)
        while len(pe) > max_ev:
            pe.pop(0)
        t["progress_events"] = pe
        try:
            pj = json.dumps(pe, default=str)
            if len(pj) > 1_500_000:
                while pe and len(pj) > 1_500_000:
                    pe.pop(0)
                    pj = json.dumps(pe, default=str)
                t["progress_events"] = pe
        except Exception:
            pj = "[]"
        t["progress_json"] = pj
    try:
        from layla.memory.db import update_background_task

        update_background_task(task_id, progress_json=pj)
    except Exception:
        pass


def _resolve_plan_binding_from_request(plan_id: str) -> tuple[str, bool]:
    """Return (active_plan_id, plan_approved) for autonomous_run when plan_id is bound."""
    pid = (plan_id or "").strip()
    if not pid:
        return "", False
    try:
        from layla.memory.db import get_layla_plan

        pr = get_layla_plan(pid)
        if not pr:
            return pid, False
        if pr.get("status") in ("approved", "executing"):
            return str(pr["id"]), True
        return str(pr["id"]), False
    except Exception:
        return pid, False


def enqueue_threaded_autonomous(req: dict, *, default_priority: int, kind: str) -> dict:
    """Queue autonomous_run in-thread (cooperative cancel) or subprocess (hard cancel), per config."""
    import runtime_safety

    goal = ((req or {}).get("message") or (req or {}).get("goal") or "").strip()
    if not goal:
        return {"ok": False, "error": "message/goal required"}
    task_id = str(uuid.uuid4())
    conversation_id = ((req or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
    sched_pri = _parse_schedule_priority(
        (req or {}).get("schedule_priority", (req or {}).get("priority")),
        default_priority,
    )
    _cog_bg: list[str] = []
    _raw_cog_bg = (req or {}).get("cognition_workspace_roots")
    if isinstance(_raw_cog_bg, list):
        _cog_bg = [str(x).strip() for x in _raw_cog_bg if str(x).strip()]
    cfg = runtime_safety.load_config()
    use_sub = bool(cfg.get("background_use_subprocess_workers"))
    ws_req = str((req or {}).get("workspace_root", "") or "").strip()
    continuous = (req or {}).get("continuous") is True
    max_iterations = max(1, min(500, int((req or {}).get("max_iterations") or 20)))
    iteration_delay_seconds = max(0.0, float((req or {}).get("iteration_delay_seconds") or 1.0))
    _bg_plan_id, _bg_plan_ok = _resolve_plan_binding_from_request(str((req or {}).get("plan_id") or ""))
    _file_plan_step_mode = (req or {}).get("file_plan_step_mode") is True
    _file_plan_id = str((req or {}).get("file_plan_id") or "").strip()

    if use_sub:
        err, sand = _compute_background_job_sandbox(cfg, ws_req)
        if err:
            return {"ok": False, "error": err}
        from services.inference_router import inference_backend_uses_local_gguf

        if inference_backend_uses_local_gguf(cfg):
            pol = str(cfg.get("background_subprocess_local_gguf_policy") or "warn").strip().lower()
            if pol == "reject":
                return {
                    "ok": False,
                    "error": "background_subprocess_local_gguf_rejected",
                    "detail": (
                        "background_use_subprocess_workers with local llama_cpp loads a separate GGUF per worker. "
                        "Set llama_server_url or ollama_base_url (or inference_backend openai_compatible/ollama) for "
                        "shared inference, or set background_subprocess_local_gguf_policy to allow."
                    ),
                }
            if pol == "warn":
                logger.warning(
                    "background_use_subprocess_workers: local llama_cpp loads a full GGUF per worker (high RAM). "
                    "Prefer llama_server_url / ollama_base_url for shared inference, or set "
                    "background_subprocess_local_gguf_policy to allow."
                )
        hist = list(get_conv_history(conversation_id))
        hist_ser = [
            {"role": str(h.get("role", "")), "content": str(h.get("content", ""))[:8000]}
            for h in hist
            if isinstance(h, dict)
        ]
        job = {
            "task_id": task_id,
            "goal": goal,
            "context": (req or {}).get("context", "") or "",
            "workspace_root": ws_req,
            "allow_write": (req or {}).get("allow_write") is True,
            "allow_run": (req or {}).get("allow_run") is True,
            "aspect_id": (req or {}).get("aspect_id", "") or "",
            "persona_focus": str((req or {}).get("persona_focus") or "").strip(),
            "show_thinking": bool((req or {}).get("show_thinking", False)),
            "conversation_id": conversation_id,
            "schedule_priority": sched_pri,
            "cognition_workspace_roots": _cog_bg,
            "sandbox_root": sand,
            "conversation_history": hist_ser,
            "continuous": continuous,
            "max_iterations": max_iterations,
            "iteration_delay_seconds": iteration_delay_seconds,
            "active_plan_id": _bg_plan_id,
            "plan_approved": _bg_plan_ok,
            "file_plan_step_mode": _file_plan_step_mode,
            "file_plan_id": _file_plan_id,
            "engineering_pipeline_mode": str((req or {}).get("engineering_pipeline_mode") or "").strip().lower(),
            "clarification_reply": str((req or {}).get("clarification_reply") or "").strip(),
        }
        payload = {
            "goal": goal,
            "context": (req or {}).get("context", "") or "",
            "workspace_root": ws_req,
            "allow_write": job["allow_write"],
            "allow_run": job["allow_run"],
            "aspect_id": job["aspect_id"],
            "persona_focus": job["persona_focus"],
            "show_thinking": job["show_thinking"],
            "conversation_id": conversation_id,
            "_schedule_priority": sched_pri,
            "_kind": kind,
            "_cognition_workspace_roots": _cog_bg,
            "_subprocess_job": job,
            "continuous": continuous,
            "max_iterations": max_iterations,
            "iteration_delay_seconds": iteration_delay_seconds,
            "active_plan_id": _bg_plan_id,
            "plan_approved": _bg_plan_ok,
            "file_plan_step_mode": _file_plan_step_mode,
            "file_plan_id": _file_plan_id,
            "engineering_pipeline_mode": job["engineering_pipeline_mode"],
            "clarification_reply": job["clarification_reply"],
        }
        thread_target = _run_background_subprocess_task
        task_row_extra = {
            "worker_mode": "subprocess",
            "worker_proc": None,
            "worker_pid": None,
        }
    else:
        cancel_event = threading.Event()
        payload = {
            "goal": goal,
            "context": (req or {}).get("context", "") or "",
            "workspace_root": ws_req,
            "allow_write": (req or {}).get("allow_write") is True,
            "allow_run": (req or {}).get("allow_run") is True,
            "aspect_id": (req or {}).get("aspect_id", "") or "",
            "persona_focus": str((req or {}).get("persona_focus") or "").strip(),
            "show_thinking": bool((req or {}).get("show_thinking", False)),
            "conversation_id": conversation_id,
            "_schedule_priority": sched_pri,
            "_kind": kind,
            "_cognition_workspace_roots": _cog_bg,
            "_cancel_event": cancel_event,
            "continuous": continuous,
            "max_iterations": max_iterations,
            "iteration_delay_seconds": iteration_delay_seconds,
            "active_plan_id": _bg_plan_id,
            "plan_approved": _bg_plan_ok,
            "file_plan_step_mode": _file_plan_step_mode,
            "file_plan_id": _file_plan_id,
            "engineering_pipeline_mode": str((req or {}).get("engineering_pipeline_mode") or "").strip().lower(),
            "clarification_reply": str((req or {}).get("clarification_reply") or "").strip(),
        }
        thread_target = _run_background_task
        task_row_extra = {"worker_mode": "thread", "cancel_event": cancel_event}

    with _TASKS_LOCK:
        task_row = {
            "task_id": task_id,
            "conversation_id": conversation_id,
            "goal": goal,
            "aspect_id": payload["aspect_id"],
            "status": "queued",
            "priority": sched_pri,
            "kind": kind,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "result": "",
            "progress_events": [],
            "progress_json": "[]",
            **task_row_extra,
        }
        _TASKS[task_id] = task_row
    try:
        from layla.memory.db import save_background_task

        save_background_task(task_row)
    except Exception:
        pass
    th = threading.Thread(
        target=thread_target,
        args=(task_id, payload),
        daemon=True,
        name=f"{kind}-{task_id[:8]}",
    )
    th.start()
    out = {
        "ok": True,
        "task_id": task_id,
        "conversation_id": conversation_id,
        "status": "queued",
        "kind": kind,
        "schedule_priority": sched_pri,
        "allow_write": payload["allow_write"],
        "allow_run": payload["allow_run"],
        "workspace_root": ws_req or None,
        "worker_mode": task_row_extra.get("worker_mode", "thread"),
        "continuous": continuous,
        "max_iterations": max_iterations,
        "iteration_delay_seconds": iteration_delay_seconds,
    }
    return out


def _task_public(task: dict) -> dict:
    """Omit non-serializable / internal fields from API responses."""
    skip = frozenset({"cancel_event", "worker_proc", "worker_pid", "progress_json"})
    out = {k: v for k, v in task.items() if k not in skip}
    pe = out.get("progress_events")
    if not isinstance(pe, list):
        pe = _parse_stored_progress_events(task.get("progress_json"))
    out["progress_events"] = pe
    try:
        import runtime_safety

        _cfg_tail = runtime_safety.load_config()
        tail_n = max(1, min(200, int(_cfg_tail.get("background_progress_tail_max", 50) or 50)))
    except (TypeError, ValueError):
        tail_n = 50
    out["progress"] = pe
    out["progress_tail"] = pe[-tail_n:] if pe else []
    return out


def _json_safe(value):
    """Convert common non-JSON Python objects into JSON-safe values."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, set):
        return [_json_safe(v) for v in sorted(value, key=lambda x: str(x))]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

def _run_background_subprocess_task(task_id: str, payload: dict) -> None:
    """Run job in a child process; hard cancel via terminate/kill on worker_proc."""
    import runtime_safety
    from services.background_subprocess import (
        cancel_worker,
        cleanup_worker_cgroup,
        spawn_background_worker,
        wait_worker_result,
    )

    now_started = datetime.now(timezone.utc).isoformat()
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        if not t:
            return
        t["status"] = "running"
        t["started_at"] = now_started
    try:
        from layla.memory.db import update_background_task

        update_background_task(task_id, status="running", started_at=now_started, error="")
    except Exception:
        pass

    cfg = runtime_safety.load_config()
    grace = float(cfg.get("background_worker_grace_seconds", 4.0))
    max_out = int(cfg.get("background_job_max_stdout_bytes", 8_000_000))
    max_err = int(cfg.get("background_job_max_stderr_bytes", 2_000_000))
    prog_on = bool(cfg.get("background_progress_stream_enabled", True))

    def _on_subproc_progress(o: dict) -> None:
        _append_progress_event(task_id, o)

    job = payload.get("_subprocess_job") or {}
    proc: subprocess.Popen | None = None
    parsed: dict | None = None
    stderr_tail = ""

    try:
        with _TASKS_LOCK:
            t2 = _TASKS.get(task_id)
            if t2 and t2.get("status") == "cancelled":
                finished_at = datetime.now(timezone.utc).isoformat()
                try:
                    from layla.memory.db import update_background_task

                    update_background_task(task_id, status="cancelled", finished_at=finished_at, error="cancelled_before_start")
                except Exception:
                    pass
                return

        proc = spawn_background_worker(job)
        with _TASKS_LOCK:
            t3 = _TASKS.get(task_id)
            if t3:
                t3["worker_proc"] = proc
                t3["worker_pid"] = proc.pid

        with _TASKS_LOCK:
            t4 = _TASKS.get(task_id)
            if t4 and t4.get("status") == "cancelled":
                cancel_worker(proc, grace_seconds=grace)
                try:
                    proc.wait(timeout=120)
                except Exception:
                    pass
                cleanup_worker_cgroup(proc)
                finished_at = datetime.now(timezone.utc).isoformat()
                try:
                    from layla.memory.db import update_background_task

                    update_background_task(task_id, status="cancelled", finished_at=finished_at, error="cancelled")
                except Exception:
                    pass
                return

        parsed, stderr_tail = wait_worker_result(
            proc,
            max_stdout_bytes=max_out,
            max_stderr_bytes=max_err,
            on_progress_event=_on_subproc_progress if prog_on else None,
        )
    except Exception as e:
        err = str(e)
        if proc is not None:
            try:
                cleanup_worker_cgroup(proc)
            except Exception:
                pass
        finished_at = datetime.now(timezone.utc).isoformat()
        with _TASKS_LOCK:
            t = _TASKS.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = err
                t["finished_at"] = finished_at
                t["worker_proc"] = None
        try:
            from layla.memory.db import update_background_task

            update_background_task(task_id, status="failed", error=err, finished_at=finished_at)
        except Exception:
            pass
        return
    finally:
        with _TASKS_LOCK:
            t5 = _TASKS.get(task_id)
            if t5:
                t5["worker_proc"] = None

    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        if t and t.get("status") == "cancelled":
            finished_at = datetime.now(timezone.utc).isoformat()
            text = ""
            if isinstance(parsed, dict) and parsed.get("ok"):
                text = str(parsed.get("response") or "")
                if not text:
                    steps = parsed.get("steps") or []
                    final = steps[-1].get("result", "") if steps else ""
                    text = final if isinstance(final, str) else json.dumps(final) if final else ""
            try:
                from layla.memory.db import update_background_task

                update_background_task(
                    task_id,
                    status="cancelled",
                    result=text,
                    finished_at=finished_at,
                    error="cancelled",
                )
            except Exception:
                pass
            return

    if parsed is None or not isinstance(parsed, dict) or not parsed.get("ok"):
        err = (parsed or {}).get("error") if isinstance(parsed, dict) else "worker_failed"
        detail = (parsed or {}).get("detail") if isinstance(parsed, dict) else ""
        msg = f"{err}: {detail}" if detail else str(err)
        if stderr_tail:
            msg = (msg + "\n" + stderr_tail[-2000:])[:8000]
        finished_at = datetime.now(timezone.utc).isoformat()
        with _TASKS_LOCK:
            t = _TASKS.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = msg
                t["finished_at"] = finished_at
        try:
            from layla.memory.db import update_background_task

            update_background_task(task_id, status="failed", error=msg, finished_at=finished_at)
        except Exception:
            pass
        return

    result = parsed
    text = str(result.get("response") or "")
    if not text:
        steps = result.get("steps") or []
        final = steps[-1].get("result", "") if steps else ""
        text = final if isinstance(final, str) else json.dumps(final) if final else ""
    finished_at = datetime.now(timezone.utc).isoformat()
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        if t and t.get("status") == "cancelled":
            try:
                from layla.memory.db import update_background_task

                update_background_task(
                    task_id,
                    status="cancelled",
                    result=text,
                    finished_at=finished_at,
                    error="cancelled",
                )
            except Exception:
                pass
            return
        if t and t.get("status") != "cancelled":
            t["status"] = "done"
            t["result"] = text
            t["state"] = result
            t["finished_at"] = finished_at
            finished_at = t["finished_at"]
        else:
            finished_at = datetime.now(timezone.utc).isoformat()
    try:
        from layla.memory.db import update_background_task

        update_background_task(task_id, status="done", result=text, finished_at=finished_at, error="")
    except Exception:
        pass


def _run_background_task(task_id: str, payload: dict) -> None:
    now_started = datetime.now(timezone.utc).isoformat()
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        if not t:
            return
        t["status"] = "running"
        t["started_at"] = now_started
    try:
        from layla.memory.db import update_background_task

        update_background_task(task_id, status="running", started_at=now_started, error="")
    except Exception:
        pass
    try:
        import runtime_safety

        _cfg_bg = runtime_safety.load_config()
        _prog_on = bool(_cfg_bg.get("background_progress_stream_enabled", True))
        _prog_cb = (lambda ev: _append_progress_event(task_id, ev)) if _prog_on else None
        sched_pri = int(payload.get("_schedule_priority", PRIORITY_BACKGROUND))
        _cog_pl = payload.get("_cognition_workspace_roots") or []
        _cev = payload.get("_cancel_event")
        _client_abort = _cev if isinstance(_cev, threading.Event) else None
        continuous = bool(payload.get("continuous"))
        max_iter = max(1, min(500, int(payload.get("max_iterations") or 20)))
        delay_s = max(0.0, float(payload.get("iteration_delay_seconds") or 1.0))

        def _effective_allows() -> tuple[bool, bool]:
            aw = bool(payload.get("allow_write"))
            ar = bool(payload.get("allow_run"))
            if bool(_cfg_bg.get("planning_strict_mode")):
                apid = str(payload.get("active_plan_id") or "").strip()
                if not apid or not payload.get("plan_approved"):
                    return False, False
            return aw, ar

        def _run_once() -> dict:
            aw, ar = _effective_allows()
            fpid = str(payload.get("file_plan_id") or "").strip()
            if fpid:
                from services.engine_plans import run_plan_iteration

                pl = dict(payload)
                pl["allow_write"] = aw
                pl["allow_run"] = ar
                pl["conversation_history"] = list(get_conv_history(payload.get("conversation_id") or ""))
                pl["client_abort_event"] = _client_abort
                pl["background_progress_callback"] = _prog_cb
                return run_plan_iteration(
                    str(payload.get("workspace_root") or ""),
                    fpid,
                    planning_strict_mode=bool(_cfg_bg.get("planning_strict_mode")),
                    payload=pl,
                )
            _bgm = str(payload.get("engineering_pipeline_mode") or "").strip().lower()
            if _bgm not in ("chat", "plan", "execute"):
                _bgm = str(_cfg_bg.get("engineering_pipeline_default_mode") or "chat").strip().lower()
            if _bgm not in ("chat", "plan", "execute"):
                _bgm = "chat"
            if not bool(_cfg_bg.get("engineering_pipeline_enabled")):
                _bgm = "chat"
            from agent_loop import autonomous_run as _autonomous_run

            return _autonomous_run(
                payload.get("goal", ""),
                context=payload.get("context", ""),
                workspace_root=payload.get("workspace_root", ""),
                allow_write=aw,
                allow_run=ar,
                conversation_history=list(get_conv_history(payload.get("conversation_id") or "")),
                aspect_id=payload.get("aspect_id", ""),
                show_thinking=bool(payload.get("show_thinking", False)),
                priority=sched_pri,
                persona_focus=str(payload.get("persona_focus") or "").strip(),
                conversation_id=str(payload.get("conversation_id") or "").strip(),
                cognition_workspace_roots=_cog_pl if _cog_pl else None,
                client_abort_event=_client_abort,
                background_progress_callback=_prog_cb,
                active_plan_id=str(payload.get("active_plan_id") or ""),
                plan_approved=bool(payload.get("plan_approved")),
                engineering_pipeline_mode=_bgm,
                clarification_reply=str(payload.get("clarification_reply") or "").strip(),
            )

        if continuous:
            if str(payload.get("file_plan_id") or "").strip():
                from services.engine_plans import run_file_plan_background_loop

                pl = dict(payload)
                pl["conversation_history"] = list(get_conv_history(payload.get("conversation_id") or ""))
                pl["client_abort_event"] = _client_abort
                pl["background_progress_callback"] = _prog_cb
                result = run_file_plan_background_loop(
                    task_id,
                    pl,
                    _client_abort,
                    _prog_cb,
                    max_iter,
                    delay_s,
                )
            else:
                from pathlib import Path

                from services.project_memory import load_project_memory

                aggregate_steps: list = []
                result = {}
                completed_iterations = 0
                for i in range(max_iter):
                    with _TASKS_LOCK:
                        t0 = _TASKS.get(task_id)
                        if t0 and t0.get("status") == "cancelled":
                            result = {
                                "status": "client_abort",
                                "response": "cancelled",
                                "steps": aggregate_steps[-300:],
                                "aspect": payload.get("aspect_id", ""),
                                "aspect_name": "Layla",
                            }
                            break
                    if _client_abort is not None and _client_abort.is_set():
                        result = {
                            "status": "client_abort",
                            "response": "cancelled",
                            "steps": aggregate_steps[-300:],
                            "aspect": payload.get("aspect_id", ""),
                            "aspect_name": "Layla",
                        }
                        break
                    if _prog_cb:
                        _prog_cb(
                            {
                                "type": "progress",
                                "phase": "continuous",
                                "iteration": i,
                                "max_iterations": max_iter,
                                "message": f"continuous iteration {i + 1}/{max_iter}",
                            }
                        )
                    result = _run_once()
                    completed_iterations += 1
                    for s in result.get("steps") or []:
                        if isinstance(s, dict):
                            aggregate_steps.append(s)
                    if len(aggregate_steps) > 500:
                        aggregate_steps = aggregate_steps[-500:]
                    if result.get("status") == "client_abort":
                        break
                    wr = str(payload.get("workspace_root") or "").strip()
                    if wr:
                        try:
                            mem = load_project_memory(Path(wr).expanduser().resolve())
                            if isinstance(mem, dict):
                                pst = (mem.get("plan") or {}).get("status")
                                if pst in ("done", "blocked"):
                                    break
                        except Exception:
                            pass
                    with _TASKS_LOCK:
                        t1 = _TASKS.get(task_id)
                        if t1 and t1.get("status") == "cancelled":
                            break
                    if _client_abort is not None and _client_abort.is_set():
                        break
                    if i < max_iter - 1 and delay_s > 0:
                        time.sleep(delay_s)
                result = dict(result)
                result["continuous_iterations"] = completed_iterations
                result["steps"] = aggregate_steps[-300:] if aggregate_steps else result.get("steps", [])
        else:
            result = _run_once()
        text = result.get("response") or ""
        if not text:
            steps = result.get("steps") or []
            final = steps[-1].get("result", "") if steps else ""
            text = final if isinstance(final, str) else json.dumps(final) if final else ""
        with _TASKS_LOCK:
            t = _TASKS.get(task_id)
            if t and t["status"] == "cancelled":
                finished_at = datetime.now(timezone.utc).isoformat()
                try:
                    from layla.memory.db import update_background_task

                    update_background_task(
                        task_id,
                        status="cancelled",
                        result=text,
                        finished_at=finished_at,
                        error="cancelled",
                    )
                except Exception:
                    pass
                return
            if t and t["status"] != "cancelled":
                t["status"] = "done"
                t["result"] = text
                t["state"] = result
                t["finished_at"] = datetime.now(timezone.utc).isoformat()
                finished_at = t["finished_at"]
            else:
                finished_at = datetime.now(timezone.utc).isoformat()
        try:
            from layla.memory.db import update_background_task

            update_background_task(task_id, status="done", result=text, finished_at=finished_at, error="")
        except Exception:
            pass
    except Exception as e:
        err = str(e)
        finished_at = datetime.now(timezone.utc).isoformat()
        with _TASKS_LOCK:
            t = _TASKS.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = err
                t["finished_at"] = finished_at
        try:
            from layla.memory.db import update_background_task

            update_background_task(task_id, status="failed", error=err, finished_at=finished_at)
        except Exception:
            pass


def _cancel_background_task_impl(task_id: str) -> JSONResponse:
    import runtime_safety
    from services.background_subprocess import cancel_worker

    grace = float(runtime_safety.load_config().get("background_worker_grace_seconds", 4.0))
    proc_to_kill: subprocess.Popen | None = None
    with _TASKS_LOCK:
        item = _TASKS.get(task_id)
        if not item:
            return JSONResponse({"ok": False, "error": "task not found"}, status_code=404)
        if item.get("status") in ("done", "failed", "cancelled"):
            return JSONResponse({"ok": True, "task": _task_public(item), "idempotent": True})
        wp = item.get("worker_proc")
        if isinstance(wp, subprocess.Popen):
            proc_to_kill = wp
        ev = item.get("cancel_event")
        if isinstance(ev, threading.Event):
            ev.set()
        item["status"] = "cancelled"
        item["finished_at"] = datetime.now(timezone.utc).isoformat()
    if proc_to_kill is not None:
        cancel_worker(proc_to_kill, grace_seconds=grace)
    try:
        from layla.memory.db import update_background_task

        update_background_task(task_id, status="cancelled", finished_at=item.get("finished_at", ""))
    except Exception:
        pass
    return JSONResponse({"ok": True, "task_id": task_id, "status": "cancelled"})
