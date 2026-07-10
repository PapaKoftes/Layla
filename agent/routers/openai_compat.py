"""OpenAI-compatible /v1/models and /v1/chat/completions."""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
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


def _extract_sampling(body: dict) -> dict:
    """BL-151: pull the standard OpenAI sampling params coding clients (Cline/Continue/
    Aider) send. Accepted gracefully; `stop` is honoured on the final text (see
    `_apply_stop`). We deliberately do NOT feed request temperature/max_tokens into the
    agent's internal decision calls — that would corrupt tool-decision JSON."""
    b = body or {}
    stop = b.get("stop")
    if isinstance(stop, str):
        stop = [stop]
    elif isinstance(stop, list):
        stop = [str(s) for s in stop if isinstance(s, str) and s]
    else:
        stop = []
    return {
        "temperature": b.get("temperature"),
        "max_tokens": b.get("max_tokens"),
        "top_p": b.get("top_p"),
        "stop": stop[:4],  # OpenAI caps stop at 4
        "seed": b.get("seed"),
    }


def _apply_stop(text: str, stop: list[str]) -> str:
    """Truncate `text` at the earliest stop sequence (OpenAI `stop` semantics)."""
    if not text or not stop:
        return text
    cut = len(text)
    for s in stop:
        i = text.find(s)
        if i != -1:
            cut = min(cut, i)
    return text[:cut]


def _v1_error(message: str, code: str = "invalid_request_error", status_code: int = 400, param: str | None = None):
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "param": param, "code": code}},
        status_code=status_code,
    )


def _vision_enabled() -> bool:
    try:
        import runtime_safety
        cfg = runtime_safety.load_config() or {}
        if cfg.get("vision_enabled"):
            return True
        feats = cfg.get("enabled_features")
        return isinstance(feats, (list, tuple, set)) and "vision" in feats
    except Exception:
        return False


def _analyze_image_part(image_url: str) -> str:
    """BL-230: turn a data-URI image part into text the text model can read.

    Decodes into the sandbox (so the existing sandbox-checked vision tools accept it),
    runs the unified analyzer, and returns a compact `[Image: … | text in image: …]`
    line. Best-effort + gated by the `vision` feature — returns "" on any failure.
    """
    if not image_url.startswith("data:image/"):
        return ""  # only local data URIs (no outbound fetch — SSRF-safe)
    import base64 as _b64
    import re as _re
    import uuid as _uuid
    from pathlib import Path as _Path
    tmp = None
    try:
        header, _, b64 = image_url.partition(",")
        # Security review Finding 2: cap the decode so a huge data-URI can't exhaust RAM/disk.
        if len(b64) > 20_000_000:  # ~15 MB decoded — plenty for a real image
            logger.warning("v1 image part rejected: base64 too large (%d chars)", len(b64))
            return ""
        ext = header.split("/", 1)[1].split(";", 1)[0] if "/" in header else "png"
        ext = {"jpeg": "jpg"}.get(ext, ext)
        ext = _re.sub(r"[^a-z0-9]", "", ext.lower())[:5] or "png"   # sanitize (no traversal)
        from layla.tools.sandbox_core import _get_sandbox
        tmp_dir = _Path(_get_sandbox()) / ".layla_vision_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f"{_uuid.uuid4().hex}.{ext}"
        tmp.write_bytes(_b64.b64decode(b64))
        from services.vision.image_analysis import analyze_image
        r = analyze_image(str(tmp))
        bits = []
        if r.get("description"):
            bits.append("Image: " + str(r["description"]).strip())
        if r.get("ocr_text"):
            bits.append("text in image: " + str(r["ocr_text"]).strip()[:1000])
        return "[" + " | ".join(bits) + "]" if bits else ""
    except Exception as e:  # noqa: BLE001
        logger.debug("v1 image part analysis skipped: %s", e)
        return ""
    finally:
        try:
            if tmp is not None and tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _normalize_openai_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        vision_on = None  # resolve lazily, only if an image part appears
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = str(part.get("type", "")).strip().lower()
            if ptype in {"text", "input_text"}:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif ptype in {"image_url", "input_image"}:
                if vision_on is None:
                    vision_on = _vision_enabled()
                if not vision_on:
                    continue
                iu = part.get("image_url")
                url = iu.get("url") if isinstance(iu, dict) else iu
                if isinstance(url, str) and url:
                    ctx = _analyze_image_part(url)
                    if ctx:
                        parts.append(ctx)
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
async def v1_chat_completions(req: dict, request: Request):
    body = req or {}
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return _v1_error("'messages' must be a non-empty array.", param="messages")
    try:
        _, parsed_aspect = _parse_v1_model(str(body.get("model", "layla") or "layla"))
    except ValueError as e:
        return _v1_error(str(e), code="model_not_found", status_code=404, param="model")

    stream = bool((req or {}).get("stream", False))
    sampling = _extract_sampling(body)  # BL-151: honour standard OpenAI params
    workspace_root = (req or {}).get("workspace_root", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    # Never let a REMOTE caller grant itself write/execute via the request body —
    # that turns the chat endpoint into an RCE primitive. Capability flags from
    # the body are honored only for a direct local caller.
    try:
        from services.safety.auth import is_direct_local
        if not is_direct_local(request.headers, request.client.host if request.client else None):
            allow_write = False
            allow_run = False
    except Exception:
        allow_write = False
        allow_run = False
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

    # Security review Finding 3: the deterministic content-guard floor lived only in the
    # autonomous_run path, so the reason-first / quick-reply / synthesize path every remote
    # caller and trivial turn takes SKIPPED it. Apply it here so it covers ALL /v1 paths.
    try:
        import runtime_safety as _rs_cg
        from services.safety.content_guard import check_input as _cg_check
        _cg = _cg_check(goal, _rs_cg.load_config())
        if _cg.blocked:
            logger.warning("content_guard: /v1 input blocked tier=%s cat=%s", _cg.tier, _cg.category)
            return _v1_error(
                "This request was blocked by the content safety filter.",
                code="content_blocked", status_code=400,
            )
    except Exception as _cg_exc:
        logger.debug("content_guard /v1 check skipped: %s", _cg_exc)

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
                    # Filter the live token stream the SAME way the /agent router does: hold an
                    # unclosed "[", strip complete [MARKER …] tags, and strip a leading persona
                    # label so control scaffolding never streams raw to an OpenAI-SDK client. The
                    # old /v1 stream emitted every token verbatim (no cleaning at all).
                    from services.agent.response_builder import stream_safe_prefix as _ssp_v1
                    _v1_emitted = 0
                    while True:
                        token = await asyncio.to_thread(tok_q.get)
                        if token is None:
                            break
                        if not token:
                            continue
                        response_text += token
                        _v1_delta, _v1_emitted = _ssp_v1(response_text, _v1_emitted)
                        if not _v1_delta:
                            continue
                        evt = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [{"index": 0, "delta": {"content": _v1_delta}, "finish_reason": None}],
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
                    response_text = final if isinstance(final, str) else ""
                # Never stream a raw tool-result dict as the answer — synthesize instead.
                from agent_loop import _looks_like_raw_tool_dict, _synthesize_direct_answer
                if (not response_text or _looks_like_raw_tool_dict(response_text)) and not result.get("refused"):
                    _direct = _synthesize_direct_answer(goal, aspect_id=aspect_id or result.get("aspect", ""))
                    if _direct:
                        response_text = _direct
                if not response_text:
                    response_text = "No response."
                # Clean the tool-run answer BEFORE chunking it to the client — this branch streamed
                # result["response"] raw (leading label / control tags leaked to OpenAI-SDK clients).
                try:
                    from services.agent.response_builder import strip_junk_from_reply as _sj_v1b
                    from services.agent.response_builder import truncate_at_next_user_turn as _tr_v1b
                    _cl_v1b = _tr_v1b(_sj_v1b(response_text))
                    if _cl_v1b.strip():
                        response_text = _cl_v1b
                except Exception:
                    pass
                for chunk in [response_text[i : i + 120] for i in range(0, len(response_text), 120)]:
                    evt = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(evt)}\n\n"
            # Clean the STORED + next-turn-context copy (the token branch's live deltas were made
            # marker-safe by stream_safe_prefix; the persisted text needs the full cleaner so a
            # leaked leading label / trailing scaffold never re-enters the model as convo context).
            try:
                from services.agent.response_builder import strip_junk_from_reply as _sj_v1
                from services.agent.response_builder import truncate_at_next_user_turn as _tr_v1
                _cleaned_v1 = _tr_v1(_sj_v1(response_text))
                if _cleaned_v1.strip():
                    response_text = _cleaned_v1
            except Exception:
                pass
            # Post-model safety floor (parity with the non-stream branch at ~line 504): the streaming
            # tokens already emitted live, but the PERSISTED + stored copy must never keep unsafe model
            # output — it would re-enter the model as conversation context on later turns.
            try:
                import runtime_safety as _rs_sout
                from services.safety.content_guard import blocked_response as _blocked_sout
                from services.safety.content_guard import check_output as _cg_sout
                _sout = _cg_sout(response_text, _rs_sout.load_config())
                if _sout.blocked:
                    logger.warning("content_guard: /v1 STREAM output blocked tier=%s cat=%s", _sout.tier, _sout.category)
                    response_text = _blocked_sout(_sout)
            except Exception:
                pass
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
    except Exception:
        # Detail is logged server-side (logger.exception); never leak exception text /
        # internal paths to the client (info disclosure — this endpoint can be remote).
        logger.exception("/v1/chat/completions failed")
        return _v1_error("Internal server error.", code="internal_server_error", status_code=500)

    response_text = (result.get("response") or "").strip()
    if not response_text:
        steps = result.get("steps") or []
        final = steps[-1].get("result", "") if steps else ""
        response_text = final if isinstance(final, str) else ""
    # A run that only made (failed) tool calls must never leak a raw tool-result dict as
    # the answer — synthesize a direct model answer to the original question instead.
    from agent_loop import _looks_like_raw_tool_dict, _synthesize_direct_answer
    if (not response_text or _looks_like_raw_tool_dict(response_text)) and not result.get("refused"):
        _direct = _synthesize_direct_answer(goal, aspect_id=aspect_id or result.get("aspect", ""))
        if _direct:
            response_text = _direct
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

    # Final safety clean: strip any leaked control markers / prompt echoes / fence loops
    # regardless of which internal path produced the text.
    try:
        from agent_loop import strip_junk_from_reply as _strip_junk
        _cleaned = _strip_junk(response_text)
        if _cleaned:
            response_text = _cleaned
        elif response_text and response_text.strip():
            # strip() emptied it → the whole reply was leaked markers with no real answer.
            # Never return the raw leak to the client; degrade to a graceful fallback.
            response_text = "No response. Try again or rephrase."
    except Exception:
        pass

    response_text = _apply_stop(response_text, sampling["stop"])  # BL-151: honour stop sequences

    # Post-model safety floor: deterministically re-check the assembled reply (symmetric
    # with the check_input on the way in). A Tier-1/Tier-2 payload the model produced is
    # replaced with a safe message before it reaches the client.
    try:
        import runtime_safety as _rs_out
        from services.safety.content_guard import blocked_response as _blocked_out
        from services.safety.content_guard import check_output as _cg_out
        _out = _cg_out(response_text, _rs_out.load_config())
        if _out.blocked:
            logger.warning("content_guard: /v1 output blocked tier=%s cat=%s", _out.tier, _out.category)
            response_text = _blocked_out(_out)
    except Exception:
        pass

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
