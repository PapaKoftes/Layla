"""Agent and learn endpoints. Mounted at / by main."""
import asyncio
import base64
import json
import logging
import queue
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent_loop import (
    _quick_reply_for_trivial_turn,
    autonomous_run,
    stream_reason,
    strip_junk_from_reply,
    truncate_at_next_user_turn,
)
from services.output_polish import polish_output
from services.resource_manager import PRIORITY_AGENT, PRIORITY_BACKGROUND, PRIORITY_CHAT, classify_load
from shared_state import (
    append_conv_history,
    get_append_history,
    get_conv_history,
    get_history,
    get_touch_activity,
)

logger = logging.getLogger("layla")
router = APIRouter(tags=["agent"])
_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()


async def _watch_client_disconnect(http_request: Request, ev: threading.Event) -> None:
    """Set ev when the HTTP client disconnects (streaming /agent only)."""
    try:
        while not ev.is_set():
            if await http_request.is_disconnected():
                ev.set()
                return
            await asyncio.sleep(0.2)
    except Exception:
        return


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


@router.get("/memories")
def search_memories(q: str = "", n: int = 8):
    """Search Layla's memories. q=query, n=max results."""
    get_touch_activity()()
    if not (q or "").strip():
        return JSONResponse({"ok": True, "memories": [], "count": 0})
    try:
        from layla.memory.vector_store import search_memories_full
        results = search_memories_full(q.strip(), k=min(n, 20), use_rerank=False)
        items = [r.get("content", "") for r in results if r.get("content")]
        return JSONResponse({"ok": True, "memories": items, "count": len(items)})
    except Exception as e:
        logger.warning("search_memories failed: %s", e)
        try:
            from layla.memory.db import search_learnings_fts
            rows = search_learnings_fts(q.strip(), n=min(n, 20))
            items = [r.get("content", "") for r in rows if r.get("content")]
            return JSONResponse({"ok": True, "memories": items, "count": len(items)})
        except Exception as e2:
            logger.warning("search_learnings_fts fallback failed: %s", e2)
            return JSONResponse({"ok": False, "error": str(e2), "memories": [], "count": 0})


@router.post("/schedule")
def schedule(req: dict):
    """Schedule a tool to run in background. tool_name, args, delay_seconds, cron_expr."""
    get_touch_activity()()
    r = req or {}
    tool_name = (r.get("tool_name") or "").strip()
    if not tool_name:
        return JSONResponse({"ok": False, "error": "tool_name required"})
    try:
        from layla.tools.registry import TOOLS, schedule_task
        if tool_name not in TOOLS:
            return JSONResponse({"ok": False, "error": f"Unknown tool: {tool_name}"})
        raw_delay = float(r.get("delay_seconds") or 0)
        delay_seconds = max(0.0, min(86400.0, raw_delay)) if not (raw_delay != raw_delay) else 0.0  # clamp 0-24h, reject NaN
        result = schedule_task(
            tool_name=tool_name,
            args=r.get("args") or {},
            delay_seconds=delay_seconds,
            cron_expr=(r.get("cron_expr") or "").strip(),
        )
        return JSONResponse(result)
    except Exception as e:
        logger.exception("schedule failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/learn/")
def learn(req: dict):
    get_touch_activity()()
    content = (req or {}).get("content", "").strip()
    kind = (req or {}).get("type", "fact") or "fact"
    tags = str((req or {}).get("tags") or "").strip()[:500]
    if not content:
        return JSONResponse({"ok": False, "error": "No content"})
    try:
        embedding_id = ""
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(content)
            meta = {"content": content, "type": kind}
            if tags:
                meta["tags"] = tags
            embedding_id = add_vector(vec, meta)
        except Exception as e:
            logger.warning("vector_store add_vector failed: %s", e)
        from layla.memory.db import save_learning
        save_learning(content=content, kind=kind, embedding_id=embedding_id, tags=tags)
        try:
            from layla.memory.memory_graph import add_node
            add_node(label=content[:80], metadata={"type": kind, "content": content})
        except Exception as e:
            logger.warning("memory_graph add_node failed: %s", e)
        return JSONResponse({"ok": True, "message": "Saved."})
    except Exception as e:
        logger.exception("learn failed")
        return JSONResponse({"ok": False, "error": str(e)})


def _get_image_context(image_url: str = "", image_base64: str = "", workspace_root: str = "") -> str:
    """
    Process attached image: fetch or decode, run describe_image/ocr_image, return context string.
    Returns empty string on failure. Saves temp file inside sandbox so tools accept it.
    """
    tmp_path = None
    try:
        try:
            import runtime_safety
            sandbox = Path(runtime_safety.load_config().get("sandbox_root", str(Path.home()))).expanduser().resolve()
        except Exception:
            sandbox = Path.home()
        if workspace_root:
            sandbox = Path(workspace_root).expanduser().resolve()
        tmp_dir = sandbox / ".layla_temp_images"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        if image_base64:
            data = image_base64
            if "," in data:
                data = data.split(",", 1)[1]
            raw = base64.b64decode(data)
            ext = ".png"
            if image_base64.startswith("data:image/jpeg") or image_base64.startswith("data:image/jpg"):
                ext = ".jpg"
            elif image_base64.startswith("data:image/webp"):
                ext = ".webp"
            elif image_base64.startswith("data:image/gif"):
                ext = ".gif"
            import uuid
            tmp_path = str(tmp_dir / f"img_{uuid.uuid4().hex[:12]}{ext}")
            Path(tmp_path).write_bytes(raw)
        elif image_url and image_url.startswith("http"):
            import urllib.request
            import uuid
            # SSRF mitigation: only http/https, block private/localhost
            try:
                from urllib.parse import urlparse
                parsed = urlparse(image_url)
                if parsed.scheme not in ("http", "https"):
                    raise ValueError("Invalid scheme")
                host = (parsed.hostname or "").lower()
                if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                    raise ValueError("Private host blocked")
                if host.startswith("127.") or host.startswith("10.") or host.startswith("169.254.") or host.startswith("192.168."):
                    raise ValueError("Private host blocked")
                if host.startswith("172."):
                    parts = host.split(".")
                    if len(parts) >= 2:
                        try:
                            b = int(parts[1])
                        except ValueError:
                            b = -1
                        if 16 <= b <= 31:
                            raise ValueError("Private host blocked")
            except Exception as e:
                logger.debug("image_url validation failed: %s", e)
            else:
                tmp_path = str(tmp_dir / f"img_{uuid.uuid4().hex[:12]}.png")
                with urllib.request.urlopen(image_url, timeout=15) as resp:
                    Path(tmp_path).write_bytes(resp.read())
        if not tmp_path or not Path(tmp_path).exists():
            return ""
        from layla.tools.registry import TOOLS
        desc = TOOLS.get("describe_image", {}).get("fn")
        ocr = TOOLS.get("ocr_image", {}).get("fn")
        caption = ""
        if desc:
            try:
                r = desc(path=tmp_path, detail="brief")
                if isinstance(r, dict) and r.get("ok"):
                    caption = (r.get("caption") or "").strip()
                    if r.get("ocr_text", "").strip():
                        caption += f" [OCR text: {r['ocr_text'][:300]}]"
            except Exception as e:
                logger.debug("describe_image failed: %s", e)
        if not caption and ocr:
            try:
                r = ocr(path=tmp_path, lang="eng")
                if isinstance(r, dict) and r.get("ok"):
                    caption = (r.get("text") or "").strip()[:500]
            except Exception as e:
                logger.debug("ocr_image failed: %s", e)
        if caption:
            return f"[Image context: {caption}]"
    except Exception as e:
        logger.debug("image context failed: %s", e)
    finally:
        if tmp_path and Path(tmp_path).exists():
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass
    return ""


def _model_ready_message() -> str | None:
    """Return error message if model/LLM is not ready, else None."""
    try:
        from services.llm_gateway import model_loaded_status
        status = model_loaded_status()
        err = status.get("error")
        if err:
            return f"Model not ready: {err}. Run python agent/first_run.py or configure runtime_config.json. See MODELS.md."
    except Exception:
        pass
    return None


def _no_model_response(message: str) -> JSONResponse:
    """Standard shape when no GGUF / remote model is configured (UI opens setup)."""
    return JSONResponse(
        {
            "error": "no_model",
            "action": "open_setup",
            "response": message,
            "state": {"status": "no_model", "steps": []},
            "aspect": "",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": [],
            "memory_influenced": [],
            "cited_sources": [],
        },
        status_code=200,
    )


@router.post("/agent/steer")
def agent_steer(req: dict):
    """Queue a short operator redirect for the in-flight run on this conversation (next decision tick)."""
    get_touch_activity()()
    hint = ((req or {}).get("hint") or (req or {}).get("steer") or (req or {}).get("message") or "").strip()
    conversation_id = ((req or {}).get("conversation_id") or "").strip()
    if not hint:
        return JSONResponse({"ok": False, "error": "hint required"}, status_code=400)
    from shared_state import push_agent_steer_hint

    push_agent_steer_hint(conversation_id, hint)
    return JSONResponse({"ok": True})


@router.post("/agent")
async def agent(req: dict, request: Request):
    get_touch_activity()()
    _history = get_history()
    _append_history = get_append_history()
    goal = (req or {}).get("message", "")
    context = (req or {}).get("context", "") or ""
    workspace_root = (req or {}).get("workspace_root", "") or ""
    image_url = (req or {}).get("image_url", "") or ""
    image_base64 = (req or {}).get("image_base64", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    aspect_id = (req or {}).get("aspect_id", "") or ""
    persona_focus = ((req or {}).get("persona_focus") or (req or {}).get("personaFocus") or "").strip()
    show_thinking = bool((req or {}).get("show_thinking", False))
    plan_mode = bool((req or {}).get("plan_mode", False))
    understand_mode = bool((req or {}).get("understand_mode", False))
    stream = bool((req or {}).get("stream", False))
    model_override = (req or {}).get("model_override", "") or ""
    reasoning_effort = "high" if (req or {}).get("reasoning_effort") == "high" else None
    conversation_id = ((req or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
    _active_plan_id, _plan_approved_flag = _resolve_plan_binding_from_request(str((req or {}).get("plan_id") or ""))
    conv_history = get_conv_history(conversation_id)
    cfg = {}
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}

    cognition_workspace_roots: list[str] = []
    project_id = ((req or {}).get("project_id") or "").strip()
    if project_id:
        try:
            import json as _json

            from layla.memory.db import get_project, set_conversation_project

            pr = get_project(project_id)
            if pr:
                if not (workspace_root or "").strip() and (pr.get("workspace_root") or "").strip():
                    workspace_root = str(pr["workspace_root"]).strip()
                pre = (pr.get("system_preamble") or "").strip()
                if pre:
                    pname = (pr.get("name") or "project").strip()
                    context = f"[Active project: {pname}]\n{pre}\n\n" + (context or "")
                ad = (pr.get("aspect_default") or "").strip()
                if ad and not (aspect_id or "").strip():
                    aspect_id = ad
                ex = (pr.get("cognition_extra_roots") or "").strip()
                if ex:
                    try:
                        parsed = _json.loads(ex)
                        if isinstance(parsed, list):
                            cognition_workspace_roots.extend(
                                str(x).strip() for x in parsed if str(x).strip()
                            )
                    except Exception:
                        pass
            try:
                set_conversation_project(conversation_id, project_id)
            except Exception:
                pass
        except Exception:
            pass
    raw_cog = (req or {}).get("cognition_workspace_roots")
    if isinstance(raw_cog, list):
        for x in raw_cog:
            s = str(x).strip()
            if s and s not in cognition_workspace_roots:
                cognition_workspace_roots.append(s)

    # Image context: if user attached image, process and prepend to context
    if image_url or image_base64:
        img_ctx = await asyncio.to_thread(_get_image_context, image_url, image_base64, workspace_root)
        if img_ctx:
            context = (img_ctx + "\n\n" + context).strip() if context else img_ctx

    # Empty message: avoid running the full loop (understand_mode may use workspace only)
    if not (goal or "").strip() and not understand_mode:
        return JSONResponse({
            "response": "Please type a message.",
            "state": {"status": "empty_message", "steps": []},
            "aspect": aspect_id or "morrigan",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": [],
            "memory_influenced": [],
            "cited_sources": [],
            "conversation_id": conversation_id,
            "load": _json_safe(classify_load()),
        }, status_code=200)

    # Understand mode: deterministic repo map + cognition sync (no full LLM loop)
    if understand_mode:
        if not (workspace_root or "").strip():
            return JSONResponse(
                {"ok": False, "error": "workspace_root required for understand_mode"},
                status_code=400,
            )
        from pathlib import Path

        from layla.tools.registry import inside_sandbox
        from services.project_memory import scan_workspace_into_memory
        from services.repo_cognition import sync_repo_cognition

        root = Path(str(workspace_root).strip()).expanduser().resolve()
        if not inside_sandbox(root):
            return JSONResponse(
                {"ok": False, "error": "workspace_root outside sandbox"},
                status_code=400,
            )
        idx_sem = (req or {}).get("understand_index_semantic") is True
        mf = int(cfg.get("project_memory_max_file_entries", 500) or 500)
        mb = int(cfg.get("project_memory_max_bytes", 1_500_000) or 1_500_000)

        def _understand_sync() -> tuple[dict, dict]:
            scan = scan_workspace_into_memory(root, dry_run=False, max_files=mf, max_bytes=mb)
            syn = sync_repo_cognition([str(root)], index_semantic=idx_sem)
            return scan, syn

        scan_out, sync_out = await asyncio.to_thread(_understand_sync)
        reply = (goal or "").strip() or "Repository map and cognition snapshot updated."
        return JSONResponse(
            {
                "response": reply,
                "state": {"status": "understand_done", "steps": []},
                "status": "understand_done",
                "aspect": aspect_id or "morrigan",
                "aspect_name": "Layla",
                "refused": False,
                "refusal_reason": "",
                "ux_states": ["understand_done"],
                "memory_influenced": [],
                "cited_sources": [],
                "conversation_id": conversation_id,
                "load": _json_safe(classify_load()),
                "scan_repo": _json_safe(scan_out),
                "sync_repo_cognition": _json_safe(sync_out),
            },
            status_code=200,
        )

    # Plan mode: generate a structured plan and return it WITHOUT executing
    if plan_mode and (goal or "").strip():
        try:
            from pathlib import Path

            from layla.tools.registry import inside_sandbox
            from services.planner import create_plan
            from services.project_memory import persist_plan_to_memory

            digest = ""
            if (workspace_root or "").strip():
                try:
                    from services.plan_workspace_store import prior_plans_digest

                    digest = prior_plans_digest(str(workspace_root).strip(), limit=8)
                except Exception:
                    digest = ""
            plan_steps = await asyncio.to_thread(create_plan, goal, 6, cfg, digest)
            from layla.memory.db import create_layla_plan, get_layla_plan
            from services.engine_plans import normalize_planner_steps

            steps_norm = normalize_planner_steps(plan_steps)
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
            if (workspace_root or "").strip() and cfg.get("project_memory_persist_plan", True):
                try:
                    wrp = Path(str(workspace_root).strip()).expanduser().resolve()
                    if inside_sandbox(wrp):
                        await asyncio.to_thread(persist_plan_to_memory, wrp, goal, plan_steps)
                except Exception:
                    pass
            return JSONResponse({
                "status": "plan_ready",
                "plan": plan_steps,
                "plan_id": plan_row_id,
                "plan_steps": steps_norm,
                "goal": goal,
                "response": "",
                "aspect": aspect_id or "morrigan",
                "aspect_name": "Layla",
                "refused": False,
                "refusal_reason": "",
                "ux_states": ["plan_ready"],
                "memory_influenced": [],
                "cited_sources": [],
            })
        except Exception as _pe:
            return JSONResponse({"ok": False, "error": f"Plan generation failed: {_pe}"}, status_code=500)

    try:
        from layla.memory.db import save_session_prompt
        save_session_prompt(goal, aspect_id or "morrigan")
    except Exception:
        pass

    # Fast path for trivial greetings/acks: avoid full orchestration overhead.
    fast_reply = _quick_reply_for_trivial_turn(goal)
    if fast_reply and not context and not image_url and not image_base64 and not show_thinking:
        fast_summary = {
            "mode": "summary_only",
            "goal": (goal or "")[:300],
            "status": "fast_path",
            "reasoning_mode": "none",
            "ux_states": ["fast_path"],
            "nodes": [{"id": "step_1", "phase": "reasoning", "action": "reason", "outcome_summary": (fast_reply or "")[:200]}],
            "final_summary": (fast_reply or "")[:280],
        }
        append_conv_history(conversation_id, "user", goal)
        append_conv_history(conversation_id, "assistant", fast_reply)
        try:
            from layla.memory.db import append_conversation_message, create_conversation

            create_conversation(conversation_id, aspect_id=aspect_id or "morrigan")
            append_conversation_message(conversation_id, "user", goal, aspect_id=aspect_id or "morrigan")
            append_conversation_message(conversation_id, "assistant", fast_reply, aspect_id=aspect_id or "morrigan")
        except Exception:
            pass
        _append_history("user", goal)
        _append_history("assistant", fast_reply)
        return JSONResponse({
            "response": fast_reply,
            "state": {
                "status": "fast_path",
                "reasoning_mode": "none",
                "reasoning_tree_summary": fast_summary,
                "steps": [],
            },
            "aspect": aspect_id or "morrigan",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": ["fast_path"],
            "memory_influenced": [],
            "cited_sources": [],
            "reasoning_mode": "none",
            "conversation_id": conversation_id,
            "reasoning_tree_summary": fast_summary,
            "load": _json_safe(classify_load()),
        }, status_code=200)

    cache_enabled = bool(cfg.get("response_cache_enabled", False))
    cache_ttl = int(cfg.get("response_cache_ttl_seconds", 300) or 0)
    cache_max_entries = int(cfg.get("response_cache_max_entries", 300) or 300)
    if cache_enabled and not stream and not allow_write and not allow_run and not context and not image_url and not image_base64:
        try:
            from services.response_cache import get_cached_response
            cached = get_cached_response(goal, aspect_id or "morrigan", cache_ttl)
            if cached:
                cached.setdefault("state", {})
                if isinstance(cached["state"], dict):
                    cached["state"]["status"] = "cache_hit"
                    cached["state"].setdefault("steps", [])
                _append_history("user", goal)
                _append_history("assistant", cached.get("response", ""))
                return JSONResponse(cached, status_code=200)
        except Exception:
            pass

    # Pre-check: model must be ready before we block on a long run
    model_err = _model_ready_message()
    if model_err and goal.strip():
        return _no_model_response(model_err)

    if stream:
        import runtime_safety as _rs_stream

        _cfg_stream = _rs_stream.load_config()
        try:
            _pulse_sec = float(_cfg_stream.get("ui_stream_keepalive_seconds", 20) or 20)
        except (TypeError, ValueError):
            _pulse_sec = 20.0
        if _pulse_sec < 0:
            _pulse_sec = 0.0

        ux_state_queue = queue.Queue()
        result_holder = []
        error_holder = []
        client_abort = threading.Event()

        def run_agent():
            try:
                r = autonomous_run(
                    goal,
                    context=context,
                    workspace_root=workspace_root,
                    allow_write=allow_write,
                    allow_run=allow_run,
                    conversation_history=list(conv_history) if conv_history else list(_history),
                    aspect_id=aspect_id,
                    show_thinking=show_thinking,
                    stream_final=True,
                    ux_state_queue=ux_state_queue,
                    model_override=model_override or None,
                    reasoning_effort=reasoning_effort,
                    priority=PRIORITY_CHAT,
                    persona_focus=persona_focus,
                    conversation_id=conversation_id,
                    cognition_workspace_roots=cognition_workspace_roots or None,
                    client_abort_event=client_abort,
                    active_plan_id=_active_plan_id,
                    plan_approved=_plan_approved_flag,
                )
                result_holder.append(r)
            except Exception as e:
                error_holder.append(e)

        thread = threading.Thread(target=run_agent)
        thread.start()

        async def agen():
            watch_task = asyncio.create_task(_watch_client_disconnect(request, client_abort))
            try:
                yield f"data: {json.dumps({'ux_state': 'thinking'})}\n\n"
                _last_stream_activity = time.monotonic()
                while thread.is_alive() or not ux_state_queue.empty():
                    try:
                        ux = await asyncio.to_thread(lambda: ux_state_queue.get(timeout=0.15))
                    except queue.Empty:
                        if (
                            _pulse_sec > 0
                            and thread.is_alive()
                            and (time.monotonic() - _last_stream_activity) >= _pulse_sec
                        ):
                            yield f"data: {json.dumps({'pulse': True})}\n\n"
                            _last_stream_activity = time.monotonic()
                        if not thread.is_alive():
                            break
                        continue
                    _last_stream_activity = time.monotonic()
                    if isinstance(ux, dict) and ux.get("_type") == "tool_start":
                        yield f"data: {json.dumps({'tool_start': ux['tool']})}\n\n"
                    elif isinstance(ux, dict) and ux.get("_type") == "think":
                        yield f"data: {json.dumps({'think': ux.get('content', ''), 'think_step': ux.get('step', 0)})}\n\n"
                    elif isinstance(ux, dict) and ux.get("_type") == "ctx_warn":
                        yield f"data: {json.dumps({'ux_state': ux.get('ux_state'), 'ctx_pct': ux.get('ctx_pct')})}\n\n"
                    else:
                        yield f"data: {json.dumps({'ux_state': ux})}\n\n"
                thread.join(timeout=0.5)
                if error_holder:
                    err = str(error_holder[0])
                    if "model" in err.lower() or "path" in err.lower():
                        err = f"Model error: {err}. Configure runtime_config.json. See MODELS.md."
                    _append_history("user", goal)
                    _append_history("assistant", err)
                    yield f"data: {json.dumps({'done': True, 'content': err, 'ux_states': [], 'memory_influenced': []})}\n\n"
                    return
                result = result_holder[0] if result_holder else {}
                if result.get("status") == "system_busy":
                    _append_history("user", goal)
                    _append_history("assistant", "I couldn't reply just then.")
                    yield f"data: {json.dumps({'done': True, 'content': 'System is under load (CPU or RAM). Try again in a moment.', 'ux_states': [], 'memory_influenced': []})}\n\n"
                    return
                if result.get("status") == "timeout":
                    _append_history("user", goal)
                    _append_history("assistant", "I couldn't reply just then.")
                    yield f"data: {json.dumps({'done': True, 'content': 'Request took too long and was stopped. Try a shorter message or try again.', 'ux_states': [], 'memory_influenced': []})}\n\n"
                    return
                if result.get("status") == "client_abort":
                    msg = result.get("response") or "Request cancelled (client disconnected)."
                    _append_history("user", goal)
                    _append_history("assistant", msg)
                    yield f"data: {json.dumps({'done': True, 'content': msg, 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'status': 'client_abort'})}\n\n"
                    return
                if result.get("status") == "stream_pending":
                    goal_for_stream = result.get("goal_for_stream", goal)
                    full = []
                    tok_q: queue.Queue = queue.Queue()

                    def _stream_worker() -> None:
                        try:
                            for t in stream_reason(
                                goal_for_stream,
                                context=context,
                                conversation_history=list(conv_history) if conv_history else list(_history),
                                aspect_id=aspect_id,
                                show_thinking=show_thinking,
                                model_override=model_override or None,
                                skip_self_reflection=(result.get("reasoning_mode") or "light") in ("none", "light"),
                                reasoning_mode_override=result.get("reasoning_mode_for_stream"),
                                precomputed_recall=result.get("precomputed_recall_for_stream"),
                                persona_focus=result.get("persona_focus_for_stream") or "",
                                workspace_root=result.get("stream_workspace_root") or workspace_root,
                                cognition_workspace_roots=result.get("cognition_workspace_roots_for_stream"),
                            ):
                                tok_q.put(t)
                        except Exception as ex:
                            logger.warning("stream_reason worker: %s", ex)
                        finally:
                            tok_q.put(None)

                    threading.Thread(target=_stream_worker, daemon=True).start()
                    _tok_empty = object()
                    _last_tok_activity = time.monotonic()
                    while True:
                        def _tok_get():
                            try:
                                return tok_q.get(timeout=0.25)
                            except queue.Empty:
                                return _tok_empty

                        _got = await asyncio.to_thread(_tok_get)
                        if _got is _tok_empty:
                            if (
                                _pulse_sec > 0
                                and (time.monotonic() - _last_tok_activity) >= _pulse_sec
                            ):
                                yield f"data: {json.dumps({'pulse': True})}\n\n"
                                _last_tok_activity = time.monotonic()
                            continue
                        token = _got
                        if token is None:
                            break
                        _last_tok_activity = time.monotonic()
                        full.append(token)
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    text = polish_output(truncate_at_next_user_turn(strip_junk_from_reply("".join(full))))
                    result["reasoning_tree_summary"] = _build_reasoning_tree_summary(result)
                    append_conv_history(conversation_id, "user", goal)
                    append_conv_history(conversation_id, "assistant", text)
                    try:
                        from layla.memory.db import append_conversation_message, create_conversation

                        create_conversation(conversation_id, aspect_id=result.get("aspect", ""))
                        append_conversation_message(conversation_id, "user", goal, aspect_id=result.get("aspect", ""))
                        append_conversation_message(conversation_id, "assistant", text, aspect_id=result.get("aspect", ""))
                    except Exception:
                        pass
                    _append_history("user", goal)
                    _append_history("assistant", text)
                    _steps_safe = []
                    try:
                        import json as _j
                        _steps_safe = [{"action": s.get("action",""), "result": s.get("result")} for s in (result.get("steps") or [])]
                        _j.dumps(_steps_safe)  # verify serialisable
                    except Exception:
                        _steps_safe = []
                    yield f"data: {json.dumps({'done': True, 'content': text, 'aspect_name': result.get('aspect_name', 'Layla'), 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'reasoning_mode': result.get('reasoning_mode'), 'conversation_id': conversation_id, 'reasoning_tree_summary': result.get('reasoning_tree_summary'), 'steps': _steps_safe})}\n\n"
                else:
                    steps = result.get("steps") or []
                    final = steps[-1].get("result", "") if steps else ""
                    response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
                    if not response_text and result.get("status") == "tool_limit":
                        response_text = "Stopped after maximum tool calls. Try a simpler request or say 'continue'."
                    if not response_text and result.get("status") == "parse_failed":
                        response_text = "I couldn't understand the request. Please rephrase."
                    if not response_text:
                        response_text = "No response. Try again or rephrase."
                    result["reasoning_tree_summary"] = _build_reasoning_tree_summary(result)
                    append_conv_history(conversation_id, "user", goal)
                    append_conv_history(conversation_id, "assistant", response_text)
                    try:
                        from layla.memory.db import append_conversation_message, create_conversation

                        create_conversation(conversation_id, aspect_id=result.get("aspect", ""))
                        append_conversation_message(conversation_id, "user", goal, aspect_id=result.get("aspect", ""))
                        append_conversation_message(conversation_id, "assistant", response_text, aspect_id=result.get("aspect", ""))
                    except Exception:
                        pass
                    _append_history("user", goal)
                    _append_history("assistant", response_text)
                    yield f"data: {json.dumps({'done': True, 'content': response_text, 'aspect_name': result.get('aspect_name', 'Layla'), 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'reasoning_mode': result.get('reasoning_mode'), 'conversation_id': conversation_id, 'reasoning_tree_summary': result.get('reasoning_tree_summary')})}\n\n"
            except Exception as e:
                logger.exception("stream_agent failed")
                err = str(e)
                if "model" in err.lower() or "path" in err.lower():
                    err = f"Model error: {err}. Configure runtime_config.json. See MODELS.md."
                yield f"data: {json.dumps({'done': True, 'content': err, 'ux_states': [], 'memory_influenced': []})}\n\n"
            finally:
                watch_task.cancel()
                try:
                    await watch_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

        return StreamingResponse(
            agen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await asyncio.to_thread(
            autonomous_run,
            goal,
            context=context,
            workspace_root=workspace_root,
            allow_write=allow_write,
            allow_run=allow_run,
            conversation_history=list(conv_history) if conv_history else list(_history),
            aspect_id=aspect_id,
            show_thinking=show_thinking,
            stream_final=stream,
            model_override=model_override or None,
            reasoning_effort=reasoning_effort,
            priority=PRIORITY_CHAT,
            persona_focus=persona_focus,
            conversation_id=conversation_id,
            cognition_workspace_roots=cognition_workspace_roots,
            active_plan_id=_active_plan_id,
            plan_approved=_plan_approved_flag,
        )
    except Exception as e:
        logger.exception("agent run failed")
        err_msg = str(e)
        if "model" in err_msg.lower() or "path" in err_msg.lower() or "file" in err_msg.lower():
            err_msg = f"Model error: {err_msg}. Configure model_filename in runtime_config.json and ensure the .gguf file exists. See MODELS.md."
        _append_history("user", goal)
        _append_history("assistant", "I couldn't reply — see error below.")
        return JSONResponse({
            "response": err_msg,
            "state": {"status": "error", "steps": []},
            "aspect": "",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": [],
            "memory_influenced": [],
            "cited_sources": [],
        })

    steps = result.get("steps") or []
    final = steps[-1].get("result", "") if steps else ""
    response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
    if not response_text and result.get("status") == "system_busy":
        response_text = "System is under load (CPU or RAM). Try again in a moment."
    elif not response_text and result.get("status") == "timeout":
        response_text = "Request took too long and was stopped. Try a shorter message or try again."
    elif not response_text and result.get("status") == "client_abort":
        response_text = result.get("response") or "Request cancelled (client disconnected)."
    elif not response_text and result.get("status") == "tool_limit":
        response_text = "Stopped after maximum tool calls. Try a simpler request or say 'continue'."
    elif not response_text and result.get("status") == "parse_failed":
        response_text = "I couldn't understand the request. Please rephrase."
    elif not response_text:
        response_text = "No response. Try again or rephrase."

    if result.get("status") == "finished":
        response_text = polish_output(response_text)
    result["reasoning_tree_summary"] = _build_reasoning_tree_summary(result)

    append_conv_history(conversation_id, "user", goal)
    append_conv_history(conversation_id, "assistant", response_text)
    try:
        from layla.memory.db import append_conversation_message, create_conversation

        create_conversation(conversation_id, aspect_id=result.get("aspect", ""))
        append_conversation_message(conversation_id, "user", goal, aspect_id=result.get("aspect", ""))
        append_conversation_message(conversation_id, "assistant", response_text, aspect_id=result.get("aspect", ""))
    except Exception:
        pass
    _append_history("user", goal)
    if result.get("status") in ("system_busy", "timeout") and response_text:
        _append_history("assistant", "I couldn't reply just then.")
    else:
        _append_history("assistant", response_text)

    _state_out = _json_safe(result)
    if isinstance(_state_out, dict):
        _state_out.setdefault("steps", [])

    response_payload = {
        "response": response_text,
        "state": _state_out,
        "aspect": result.get("aspect", ""),
        "aspect_name": result.get("aspect_name", "Layla"),
        "refused": result.get("refused", False),
        "refusal_reason": _json_safe(result.get("refusal_reason", "")),
        "ux_states": _json_safe(result.get("ux_states", [])),
        "memory_influenced": _json_safe(result.get("memory_influenced", [])),
        "cited_sources": _json_safe(result.get("cited_knowledge_sources", [])),
        "reasoning_mode": result.get("reasoning_mode"),
        "conversation_id": conversation_id,
        "load": _json_safe(classify_load()),
        "reasoning_tree_summary": _json_safe(result.get("reasoning_tree_summary", {})),
    }
    if cache_enabled and not stream and not allow_write and not allow_run and not context and not image_url and not image_base64:
        try:
            from services.response_cache import put_cached_response
            put_cached_response(goal, aspect_id or response_payload.get("aspect") or "morrigan", response_payload, max_entries=cache_max_entries)
        except Exception:
            pass
    return JSONResponse(response_payload)


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
            return autonomous_run(
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


@router.post("/resume")
async def resume_paused(req: dict):
    """Resume a paused-high-load run from its checkpoint. Pass the checkpoint from the paused response."""
    checkpoint = (req or {}).get("checkpoint") or {}
    if not checkpoint:
        return JSONResponse({"ok": False, "error": "checkpoint required"}, status_code=400)
    goal = checkpoint.get("goal") or checkpoint.get("original_goal") or ""
    if not goal:
        return JSONResponse({"ok": False, "error": "checkpoint missing goal"}, status_code=400)
    workspace_root = (req or {}).get("workspace_root", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    aspect_id = (req or {}).get("aspect_id", "") or ""
    from agent_loop import autonomous_run
    result = await asyncio.to_thread(
        autonomous_run,
        goal,
        context=f"[Resuming from checkpoint — {len(checkpoint.get('steps', []))} steps already done]",
        workspace_root=workspace_root,
        allow_write=allow_write,
        allow_run=allow_run,
        conversation_history=[],
        aspect_id=aspect_id or "morrigan",
        conversation_id=str((req or {}).get("conversation_id") or "").strip(),
    )
    return JSONResponse({
        "ok": True,
        "status": result.get("status"),
        "response": (result.get("steps") or [{}])[-1].get("result", "") if result.get("steps") else "",
        "state": result,
    })


@router.post("/execute_plan")
async def execute_plan_route(req: dict):
    """Execute a pre-generated plan (from plan_mode). Steps run sequentially via autonomous_run."""
    plan_steps = (req or {}).get("plan") or []
    goal = (req or {}).get("goal", "") or ""
    workspace_root = (req or {}).get("workspace_root", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    aspect_id = (req or {}).get("aspect_id", "") or ""
    try:
        dm = int((req or {}).get("default_max_retries") or (req or {}).get("step_max_retries") or 1)
    except (TypeError, ValueError):
        dm = 1
    dm = max(0, min(3, dm))
    if not plan_steps or not goal:
        return JSONResponse({"ok": False, "error": "plan and goal are required"}, status_code=400)
    try:
        from services.planner import execute_plan as _exec_plan
        from agent_loop import autonomous_run
        results = await asyncio.to_thread(
            _exec_plan,
            plan_steps,
            autonomous_run,
            "",  # goal_prefix
            0,   # plan_depth
            step_governance=True,
            default_max_retries=dm,
            workspace_root=workspace_root,
            allow_write=allow_write,
            allow_run=allow_run,
            aspect_id=aspect_id or "morrigan",
            conversation_id=str((req or {}).get("conversation_id") or "").strip(),
            plan_approved=True,
            active_plan_id=str((req or {}).get("plan_id") or "").strip(),
        )
        all_ok = bool(results.get("all_steps_ok")) if isinstance(results, dict) else False
        return JSONResponse({
            "ok": True,
            "status": "plan_executed",
            "results": results,
            "goal": goal,
            "all_steps_ok": all_ok,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/agent/background")
def start_background(req: dict):
    get_touch_activity()()
    out = enqueue_threaded_autonomous(req or {}, default_priority=PRIORITY_BACKGROUND, kind="background")
    if not out.get("ok"):
        return JSONResponse(out, status_code=400)
    return JSONResponse(
        {
            "ok": True,
            "task_id": out["task_id"],
            "conversation_id": out["conversation_id"],
            "status": out["status"],
            "allow_write": out.get("allow_write"),
            "allow_run": out.get("allow_run"),
            "workspace_root": out.get("workspace_root"),
            "worker_mode": out.get("worker_mode", "thread"),
        }
    )


@router.get("/agent/tasks")
def list_background_tasks():
    with _TASKS_LOCK:
        items = list(_TASKS.values())
    # Merge persisted rows so completed tasks survive restarts.
    try:
        from layla.memory.db import list_background_tasks as _list_background_tasks_db

        db_items = _list_background_tasks_db(limit=200)
        merged: dict[str, dict] = {}
        for row in db_items:
            rid = row.get("id", "")
            if not rid:
                continue
            merged[rid] = {
                "task_id": rid,
                "conversation_id": row.get("conversation_id", ""),
                "goal": row.get("goal", ""),
                "aspect_id": row.get("aspect_id", ""),
                "status": row.get("status", "queued"),
                "priority": row.get("priority", PRIORITY_BACKGROUND),
                "kind": row.get("kind", "") or "background",
                "created_at": row.get("created_at", ""),
                "started_at": row.get("started_at", ""),
                "finished_at": row.get("finished_at", ""),
                "result": row.get("result", ""),
                "error": row.get("error", ""),
                "progress_events": _parse_stored_progress_events(row.get("progress_json")),
            }
        for item in items:
            tid = item.get("task_id", "")
            if tid:
                merged[tid] = item
        items = list(merged.values())
    except Exception:
        pass
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items = [_task_public(x) if isinstance(x, dict) else x for x in items]
    return JSONResponse({"ok": True, "tasks": items})


@router.get("/agent/tasks/{task_id}")
def get_background_task(task_id: str):
    with _TASKS_LOCK:
        item = _TASKS.get(task_id)
    if not item:
        try:
            from layla.memory.db import get_background_task as _get_background_task_db

            row = _get_background_task_db(task_id)
            if row:
                item = {
                    "task_id": row.get("id", task_id),
                    "conversation_id": row.get("conversation_id", ""),
                    "goal": row.get("goal", ""),
                    "aspect_id": row.get("aspect_id", ""),
                    "status": row.get("status", "queued"),
                    "priority": row.get("priority", PRIORITY_BACKGROUND),
                    "kind": row.get("kind", "") or "background",
                    "created_at": row.get("created_at", ""),
                    "started_at": row.get("started_at", ""),
                    "finished_at": row.get("finished_at", ""),
                    "result": row.get("result", ""),
                    "error": row.get("error", ""),
                    "progress_events": _parse_stored_progress_events(row.get("progress_json")),
                }
        except Exception:
            pass
    if not item:
        return JSONResponse({"ok": False, "error": "task not found"}, status_code=404)
    return JSONResponse({"ok": True, "task": _task_public(item) if isinstance(item, dict) else item})


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


@router.delete("/agent/tasks/{task_id}")
def cancel_background_task_delete(task_id: str):
    """Best-effort cooperative cancel: sets client_abort_event on the background run."""
    get_touch_activity()()
    return _cancel_background_task_impl(task_id)


@router.post("/agent/tasks/{task_id}/cancel")
def cancel_background_task_post(task_id: str):
    """Same as DELETE /agent/tasks/{task_id} — for clients that prefer POST."""
    get_touch_activity()()
    return _cancel_background_task_impl(task_id)
