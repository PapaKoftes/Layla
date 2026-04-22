"""OpenAI-compatible /v1/models and /v1/chat/completions."""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import time
import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from agent_loop import _quick_reply_for_trivial_turn, autonomous_run, stream_reason
from shared_state import get_append_history

logger = logging.getLogger("layla")
router = APIRouter(tags=["openai"])


@router.get("/v1/models")
def v1_models():
    base = {"object": "model", "created": 1700000000, "owned_by": "local"}
    try:
        import orchestrator as _orch

        aspect_ids = [str(a.get("id", "")).strip() for a in (_orch._load_aspects() or []) if str(a.get("id", "")).strip()]
    except Exception:
        aspect_ids = ["morrigan", "nyx", "echo", "eris", "cassandra", "lilith"]
    models = [{"id": "layla", **base}]
    models.extend({"id": f"layla-{aid}", **base} for aid in aspect_ids)
    return JSONResponse({"object": "list", "data": models})


def _v1_error(message: str, code: str = "invalid_request_error", status_code: int = 400, param: str | None = None):
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "param": param, "code": code}},
        status_code=status_code,
    )


def _normalize_openai_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = str(part.get("type", "")).strip().lower()
            if ptype in {"text", "input_text"}:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _parse_v1_model(model_name: str) -> tuple[str, str]:
    raw = (model_name or "layla").strip()
    if raw == "layla":
        return raw, ""
    if raw.startswith("layla-"):
        aspect = raw[len("layla-") :].strip()
        if aspect:
            return raw, aspect
    raise ValueError(f"Unsupported model '{raw}'. Use 'layla' or 'layla-<aspect_id>'.")


@router.post("/v1/chat/completions")
async def v1_chat_completions(req: dict):
    body = req or {}
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return _v1_error("'messages' must be a non-empty array.", param="messages")
    try:
        _, parsed_aspect = _parse_v1_model(str(body.get("model", "layla") or "layla"))
    except ValueError as e:
        return _v1_error(str(e), code="model_not_found", status_code=404, param="model")

    stream = bool((req or {}).get("stream", False))
    workspace_root = (req or {}).get("workspace_root", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    aspect_id = (req or {}).get("aspect_id", "") or parsed_aspect
    show_thinking = bool((req or {}).get("show_thinking", False))
    conversation_id = ((req or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    goal = ""
    system_ctx = ""
    conversation_history: list[dict[str, str]] = []
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = (msg.get("role", "") or "").strip()
        content = _normalize_openai_content(msg.get("content", ""))
        if role == "system":
            system_ctx = f"{system_ctx}\n{content}".strip() if content else system_ctx
            continue
        if role not in ("user", "assistant"):
            continue
        is_last = idx == (len(messages) - 1)
        if role == "user" and is_last:
            goal = content
        else:
            conversation_history.append({"role": role, "content": content})

    if not goal and messages:
        for msg in reversed(messages):
            if isinstance(msg, dict) and (msg.get("role", "") or "").strip() == "user":
                goal = _normalize_openai_content(msg.get("content", ""))
                break

    if not goal:
        return _v1_error("No user message content found in 'messages'.", param="messages")

    append_h = get_append_history()

    if stream:

        async def gen():
            response_text = ""
            model_name = f"layla-{aspect_id or 'morrigan'}"
            first_evt = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(first_evt)}\n\n"
            if not allow_write and not allow_run:
                quick = _quick_reply_for_trivial_turn(goal)
                if quick:
                    response_text = quick
                    evt = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {"content": quick}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(evt)}\n\n"
                else:
                    progress_evt = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                        "layla_progress": {"state": "waiting_first_token"},
                    }
                    yield f"data: {json.dumps(progress_evt)}\n\n"
                    tok_q: queue.Queue = queue.Queue()

                    def _stream_worker() -> None:
                        try:
                            gen_tokens = stream_reason(
                                goal=goal,
                                context=system_ctx,
                                conversation_history=conversation_history,
                                aspect_id=aspect_id,
                                show_thinking=show_thinking,
                            )
                            for t in gen_tokens:
                                tok_q.put(t)
                        except Exception as ex:
                            logger.warning("v1 stream worker: %s", ex)
                        finally:
                            tok_q.put(None)

                    import threading as _threading
                    _threading.Thread(target=_stream_worker, daemon=True).start()
                    while True:
                        token = await asyncio.to_thread(tok_q.get)
                        if token is None:
                            break
                        if not token:
                            continue
                        response_text += token
                        evt = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(evt)}\n\n"
            else:
                result = await asyncio.to_thread(
                    autonomous_run,
                    goal,
                    context=system_ctx,
                    workspace_root=workspace_root,
                    allow_write=allow_write,
                    allow_run=allow_run,
                    conversation_history=conversation_history,
                    aspect_id=aspect_id,
                    show_thinking=show_thinking,
                    conversation_id=conversation_id,
                )
                model_name = f"layla-{result.get('aspect', aspect_id or 'morrigan')}"
                response_text = (result.get("response") or "").strip()
                if not response_text:
                    steps = result.get("steps") or []
                    final = steps[-1].get("result", "") if steps else ""
                    response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
                if not response_text:
                    response_text = "No response."
                for chunk in [response_text[i : i + 120] for i in range(0, len(response_text), 120)]:
                    evt = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(evt)}\n\n"
            if not response_text:
                response_text = "No response."
            done_evt = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            append_h("user", goal)
            append_h("assistant", response_text)
            try:
                from layla.memory.db import append_conversation_message, create_conversation

                create_conversation(conversation_id, aspect_id=aspect_id)
                append_conversation_message(conversation_id, "user", goal, aspect_id=aspect_id)
                append_conversation_message(conversation_id, "assistant", response_text, aspect_id=aspect_id)
            except Exception:
                pass
            yield f"data: {json.dumps(done_evt)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    if not allow_write and not allow_run:
        quick = _quick_reply_for_trivial_turn(goal)
        if quick:
            response_text = quick
            append_h("user", goal)
            append_h("assistant", response_text)
            try:
                from layla.memory.db import append_conversation_message, create_conversation

                create_conversation(conversation_id, aspect_id=aspect_id)
                append_conversation_message(conversation_id, "user", goal, aspect_id=aspect_id)
                append_conversation_message(conversation_id, "assistant", response_text, aspect_id=aspect_id)
            except Exception:
                pass
            return JSONResponse({
                "id": completion_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": f"layla-{aspect_id or 'morrigan'}",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": len((goal or "").split()),
                    "completion_tokens": len((response_text or "").split()),
                    "total_tokens": len((goal or "").split()) + len((response_text or "").split()),
                },
                "aspect": aspect_id or "morrigan",
                "conversation_id": conversation_id,
            })

    try:
        result = await asyncio.to_thread(
            autonomous_run,
            goal,
            context=system_ctx,
            workspace_root=workspace_root,
            allow_write=allow_write,
            allow_run=allow_run,
            conversation_history=conversation_history,
            aspect_id=aspect_id,
            show_thinking=show_thinking,
            conversation_id=conversation_id,
        )
    except Exception as e:
        logger.exception("/v1/chat/completions failed")
        return _v1_error(f"Internal server error: {e}", code="internal_server_error", status_code=500)

    response_text = (result.get("response") or "").strip()
    if not response_text:
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

    append_h("user", goal)
    append_h("assistant", response_text)
    try:
        from layla.memory.db import append_conversation_message, create_conversation

        create_conversation(conversation_id, aspect_id=result.get("aspect", ""))
        append_conversation_message(conversation_id, "user", goal, aspect_id=result.get("aspect", ""))
        append_conversation_message(conversation_id, "assistant", response_text, aspect_id=result.get("aspect", ""))
    except Exception:
        pass

    return JSONResponse({
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"layla-{result.get('aspect', aspect_id or 'morrigan')}",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": len((goal or "").split()),
            "completion_tokens": len((response_text or "").split()),
            "total_tokens": len((goal or "").split()) + len((response_text or "").split()),
        },
        "aspect": result.get("aspect", ""),
        "conversation_id": conversation_id,
    })
