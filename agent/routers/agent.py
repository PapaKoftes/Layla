"""Agent and learn endpoints. Mounted at / by main."""
import asyncio
import base64
import json
import logging
import queue
import re
import threading
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from agent_loop import (
    autonomous_run,
    stream_reason,
    strip_junk_from_reply,
    truncate_at_next_user_turn,
)
from services.output_polish import polish_output
from shared_state import get_append_history, get_history, get_touch_activity

logger = logging.getLogger("layla")
router = APIRouter(tags=["agent"])
_TRIVIAL_PATTERNS = re.compile(r"^(hi|hello|hey|yo|sup|ok|okay|sure|thanks|ty|lol|k|thx)\W*$", re.IGNORECASE)


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
    if not content:
        return JSONResponse({"ok": False, "error": "No content"})
    try:
        embedding_id = ""
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(content)
            embedding_id = add_vector(vec, {"content": content, "type": kind})
        except Exception as e:
            logger.warning("vector_store add_vector failed: %s", e)
        from layla.memory.db import save_learning
        save_learning(content=content, kind=kind, embedding_id=embedding_id)
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


def _trivial_fast_reply(goal: str, aspect_id: str) -> str | None:
    text = (goal or "").strip()
    if not text or len(text) > 20:
        return None
    if not _TRIVIAL_PATTERNS.match(text):
        return None
    if text.lower().startswith(("thanks", "thx", "ty")):
        return "Anytime. Want to keep going?"
    return "Hey. I am here. What do you want to work on?"


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
    show_thinking = bool((req or {}).get("show_thinking", False))
    stream = bool((req or {}).get("stream", False))
    model_override = (req or {}).get("model_override", "") or ""
    reasoning_effort = "high" if (req or {}).get("reasoning_effort") == "high" else None
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
    fast_reply = _trivial_fast_reply(goal, aspect_id)
    if fast_reply and not context and not image_url and not image_base64 and not show_thinking:
        _append_history("user", goal)
        _append_history("assistant", fast_reply)
        return JSONResponse({
            "response": fast_reply,
            "state": {"status": "fast_path", "reasoning_mode": "none"},
            "aspect": aspect_id or "morrigan",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": ["fast_path"],
            "memory_influenced": [],
            "cited_sources": [],
            "reasoning_mode": "none",
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
                    conversation_history=list(_history),
                    aspect_id=aspect_id,
                    show_thinking=show_thinking,
                    stream_final=True,
                    ux_state_queue=ux_state_queue,
                    model_override=model_override or None,
                    reasoning_effort=reasoning_effort,
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
                        conversation_history=list(_history),
                        aspect_id=aspect_id,
                        show_thinking=show_thinking,
                        model_override=model_override or None,
                        skip_self_reflection=(result.get("reasoning_mode") or "light") in ("none", "light"),
                    ):
                        full.append(token)
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    text = polish_output(truncate_at_next_user_turn(strip_junk_from_reply("".join(full))))
                    _append_history("user", goal)
                    _append_history("assistant", text)
                    yield f"data: {json.dumps({'done': True, 'content': text, 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'reasoning_mode': result.get('reasoning_mode')})}\n\n"
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
                    _append_history("user", goal)
                    _append_history("assistant", response_text)
                    yield f"data: {json.dumps({'done': True, 'content': response_text, 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'reasoning_mode': result.get('reasoning_mode')})}\n\n"
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
            conversation_history=list(_history),
            aspect_id=aspect_id,
            show_thinking=show_thinking,
            stream_final=stream,
            model_override=model_override or None,
            reasoning_effort=reasoning_effort,
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

    _append_history("user", goal)
    if result.get("status") in ("system_busy", "timeout") and response_text:
        _append_history("assistant", "I couldn't reply just then.")
    else:
        _append_history("assistant", response_text)

    response_payload = {
        "response": response_text,
        "state": result,
        "aspect": result.get("aspect", ""),
        "aspect_name": result.get("aspect_name", "Layla"),
        "refused": result.get("refused", False),
        "refusal_reason": result.get("refusal_reason", ""),
        "ux_states": result.get("ux_states", []),
        "memory_influenced": result.get("memory_influenced", []),
        "cited_sources": result.get("cited_knowledge_sources", []),
        "reasoning_mode": result.get("reasoning_mode"),
    }
    if cache_enabled and not stream and not allow_write and not allow_run and not context and not image_url and not image_base64:
        try:
            from services.response_cache import put_cached_response
            put_cached_response(goal, aspect_id or response_payload.get("aspect") or "morrigan", response_payload, max_entries=cache_max_entries)
        except Exception:
            pass
    return JSONResponse(response_payload)
