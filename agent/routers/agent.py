"""Agent and learn endpoints. Mounted at / by main."""
import asyncio
import base64
import json
import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from agent_loop import (
    _quick_reply_for_trivial_turn,
    autonomous_run,
    stream_reason,
    strip_junk_from_reply,
    truncate_at_next_user_turn,
)
from services.output_polish import polish_output
from services.resource_manager import PRIORITY_BACKGROUND, PRIORITY_CHAT, classify_load
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
                if host.startswith("127.") or host.startswith("10.") or host.startswith("169.254."):
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
            "state": {},
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


@router.post("/agent")
async def agent(req: dict):
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
    stream = bool((req or {}).get("stream", False))
    model_override = (req or {}).get("model_override", "") or ""
    reasoning_effort = "high" if (req or {}).get("reasoning_effort") == "high" else None
    conversation_id = ((req or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
    conv_history = get_conv_history(conversation_id)
    cfg = {}
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}

    # Image context: if user attached image, process and prepend to context
    if image_url or image_base64:
        img_ctx = await asyncio.to_thread(_get_image_context, image_url, image_base64, workspace_root)
        if img_ctx:
            context = (img_ctx + "\n\n" + context).strip() if context else img_ctx

    # Empty message: avoid running the full loop
    if not (goal or "").strip():
        return JSONResponse({
            "response": "Please type a message.",
            "state": {},
            "aspect": aspect_id or "morrigan",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": [],
            "memory_influenced": [],
            "cited_sources": [],
        }, status_code=200)

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
            "state": {"status": "fast_path", "reasoning_mode": "none", "reasoning_tree_summary": fast_summary},
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
        ux_state_queue = queue.Queue()
        result_holder = []
        error_holder = []

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
                )
                result_holder.append(r)
            except Exception as e:
                error_holder.append(e)

        thread = threading.Thread(target=run_agent)
        thread.start()

        def gen():
            try:
                yield f"data: {json.dumps({'ux_state': 'thinking'})}\n\n"
                while thread.is_alive() or not ux_state_queue.empty():
                    try:
                        ux = ux_state_queue.get(timeout=0.15)
                        if isinstance(ux, dict) and ux.get("_type") == "tool_start":
                            yield f"data: {json.dumps({'tool_start': ux['tool']})}\n\n"
                        else:
                            yield f"data: {json.dumps({'ux_state': ux})}\n\n"
                    except queue.Empty:
                        if not thread.is_alive():
                            break
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
                if result.get("status") == "stream_pending":
                    goal_for_stream = result.get("goal_for_stream", goal)
                    full = []
                    for token in stream_reason(
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
                    ):
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
                    yield f"data: {json.dumps({'done': True, 'content': text, 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'reasoning_mode': result.get('reasoning_mode'), 'conversation_id': conversation_id, 'reasoning_tree_summary': result.get('reasoning_tree_summary')})}\n\n"
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
                    yield f"data: {json.dumps({'done': True, 'content': response_text, 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'reasoning_mode': result.get('reasoning_mode'), 'conversation_id': conversation_id, 'reasoning_tree_summary': result.get('reasoning_tree_summary')})}\n\n"
            except Exception as e:
                logger.exception("stream_agent failed")
                err = str(e)
                if "model" in err.lower() or "path" in err.lower():
                    err = f"Model error: {err}. Configure runtime_config.json. See MODELS.md."
                yield f"data: {json.dumps({'done': True, 'content': err, 'ux_states': [], 'memory_influenced': []})}\n\n"

        return StreamingResponse(
            gen(),
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
            "state": {},
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

    response_payload = {
        "response": response_text,
        "state": _json_safe(result),
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
        result = autonomous_run(
            payload.get("goal", ""),
            context=payload.get("context", ""),
            workspace_root=payload.get("workspace_root", ""),
            allow_write=bool(payload.get("allow_write")),
            allow_run=bool(payload.get("allow_run")),
            conversation_history=list(get_conv_history(payload.get("conversation_id") or "")),
            aspect_id=payload.get("aspect_id", ""),
            show_thinking=bool(payload.get("show_thinking", False)),
            priority=PRIORITY_BACKGROUND,
            persona_focus=str(payload.get("persona_focus") or "").strip(),
        )
        text = result.get("response") or ""
        if not text:
            steps = result.get("steps") or []
            final = steps[-1].get("result", "") if steps else ""
            text = final if isinstance(final, str) else json.dumps(final) if final else ""
        with _TASKS_LOCK:
            t = _TASKS.get(task_id)
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


@router.post("/agent/background")
def start_background(req: dict):
    get_touch_activity()()
    goal = ((req or {}).get("message") or (req or {}).get("goal") or "").strip()
    if not goal:
        return JSONResponse({"ok": False, "error": "message/goal required"})
    task_id = str(uuid.uuid4())
    conversation_id = ((req or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
    payload = {
        "goal": goal,
        "context": (req or {}).get("context", "") or "",
        "workspace_root": (req or {}).get("workspace_root", "") or "",
        "allow_write": (req or {}).get("allow_write") is True,
        "allow_run": (req or {}).get("allow_run") is True,
        "aspect_id": (req or {}).get("aspect_id", "") or "",
        "persona_focus": str((req or {}).get("persona_focus") or "").strip(),
        "show_thinking": bool((req or {}).get("show_thinking", False)),
        "conversation_id": conversation_id,
    }
    with _TASKS_LOCK:
        task_row = {
            "task_id": task_id,
            "conversation_id": conversation_id,
            "goal": goal,
            "aspect_id": payload["aspect_id"],
            "status": "queued",
            "priority": PRIORITY_BACKGROUND,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "result": "",
        }
        _TASKS[task_id] = task_row
    try:
        from layla.memory.db import save_background_task

        save_background_task(task_row)
    except Exception:
        pass
    th = threading.Thread(target=_run_background_task, args=(task_id, payload), daemon=True, name=f"bg-task-{task_id[:8]}")
    th.start()
    return JSONResponse({"ok": True, "task_id": task_id, "conversation_id": conversation_id, "status": "queued"})


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
                "created_at": row.get("created_at", ""),
                "started_at": row.get("started_at", ""),
                "finished_at": row.get("finished_at", ""),
                "result": row.get("result", ""),
                "error": row.get("error", ""),
            }
        for item in items:
            tid = item.get("task_id", "")
            if tid:
                merged[tid] = item
        items = list(merged.values())
    except Exception:
        pass
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
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
                    "created_at": row.get("created_at", ""),
                    "started_at": row.get("started_at", ""),
                    "finished_at": row.get("finished_at", ""),
                    "result": row.get("result", ""),
                    "error": row.get("error", ""),
                }
        except Exception:
            pass
    if not item:
        return JSONResponse({"ok": False, "error": "task not found"}, status_code=404)
    return JSONResponse({"ok": True, "task": item})


@router.delete("/agent/tasks/{task_id}")
def cancel_background_task(task_id: str):
    with _TASKS_LOCK:
        item = _TASKS.get(task_id)
        if not item:
            return JSONResponse({"ok": False, "error": "task not found"}, status_code=404)
        if item.get("status") in ("done", "failed", "cancelled"):
            return JSONResponse({"ok": True, "task": item, "idempotent": True})
        item["status"] = "cancelled"
        item["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        from layla.memory.db import update_background_task

        update_background_task(task_id, status="cancelled", finished_at=item.get("finished_at", ""))
    except Exception:
        pass
    return JSONResponse({"ok": True, "task_id": task_id, "status": "cancelled"})
