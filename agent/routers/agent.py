"""Agent and learn endpoints. Mounted at / by main."""
import asyncio
import json
import logging
import queue
import threading
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from shared_state import get_touch_activity, get_history, get_append_history
from agent_loop import (
    autonomous_run,
    stream_reason,
    strip_junk_from_reply,
    truncate_at_next_user_turn,
)

logger = logging.getLogger("layla")
router = APIRouter(tags=["agent"])


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
            from layla.memory.vector_store import embed, add_vector
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


@router.post("/agent")
async def agent(req: dict):
    get_touch_activity()()
    _history = get_history()
    _append_history = get_append_history()
    goal = (req or {}).get("message", "")
    context = (req or {}).get("context", "") or ""
    workspace_root = (req or {}).get("workspace_root", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    aspect_id = (req or {}).get("aspect_id", "") or ""
    show_thinking = bool((req or {}).get("show_thinking", False))
    stream = bool((req or {}).get("stream", False))

    if stream:
        ux_state_queue = queue.Queue()
        result_holder = []

        def run_agent():
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
            )
            result_holder.append(r)

        thread = threading.Thread(target=run_agent)
        thread.start()

        def gen():
            try:
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
                result = result_holder[0] if result_holder else {}
                if result.get("status") == "stream_pending":
                    goal_for_stream = result.get("goal_for_stream", goal)
                    full = []
                    for token in stream_reason(
                        goal_for_stream,
                        context=context,
                        conversation_history=list(_history),
                        aspect_id=aspect_id,
                        show_thinking=show_thinking,
                    ):
                        full.append(token)
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    text = truncate_at_next_user_turn(strip_junk_from_reply("".join(full)))
                    _append_history("user", goal)
                    _append_history("assistant", text)
                    yield f"data: {json.dumps({'done': True, 'content': text, 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', [])})}\n\n"
                else:
                    steps = result.get("steps") or []
                    final = steps[-1].get("result", "") if steps else ""
                    response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
                    _append_history("user", goal)
                    _append_history("assistant", response_text)
                    yield f"data: {json.dumps({'done': True, 'content': response_text, 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', [])})}\n\n"
            except Exception as e:
                logger.exception("stream_agent failed")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
    )

    steps = result.get("steps") or []
    final = steps[-1].get("result", "") if steps else ""
    response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
    if not response_text and result.get("status") == "system_busy":
        response_text = "System is under load (CPU or RAM). Try again in a moment."
    elif not response_text and result.get("status") == "timeout":
        response_text = "Request took too long and was stopped. Try a shorter message or try again."

    _append_history("user", goal)
    if result.get("status") in ("system_busy", "timeout") and response_text:
        _append_history("assistant", "I couldn't reply just then.")
    else:
        _append_history("assistant", response_text)

    return JSONResponse({
        "response": response_text,
        "state": result,
        "aspect": result.get("aspect", ""),
        "aspect_name": result.get("aspect_name", "Layla"),
        "refused": result.get("refused", False),
        "refusal_reason": result.get("refusal_reason", ""),
        "ux_states": result.get("ux_states", []),
        "memory_influenced": result.get("memory_influenced", []),
        "cited_sources": result.get("cited_knowledge_sources", []),
    })
