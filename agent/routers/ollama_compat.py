"""Ollama-native API surface (UPG-41 / BL-152).

Lets any tool that speaks Ollama's HTTP API (Open WebUI, ollama-python, editor plugins, …)
point straight at Layla. We translate Ollama's `/api/chat` + `/api/generate` into the existing
OpenAI-compatible handler (so all of the agent logic, aspect routing, and the local-only
write/run security carry over untouched), and expose `/api/tags` + `/api/version` for discovery.
Streaming is coerced to a single final message (non-stream) for now.
"""
from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["ollama"])


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _aspect_ids() -> list[str]:
    try:
        from services.personality.character_creator import all_aspect_ids
        return list(all_aspect_ids())
    except Exception:
        return ["morrigan", "nyx", "echo", "eris", "cassandra", "lilith"]


def _json_of(resp) -> dict:
    """Extract the JSON dict from a JSONResponse (or a plain dict)."""
    if isinstance(resp, JSONResponse):
        try:
            return json.loads(resp.body)
        except Exception:
            return {}
    return resp if isinstance(resp, dict) else {}


def _content_of(resp) -> tuple[str, dict]:
    d = _json_of(resp)
    content = ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
    return content, d


@router.get("/api/version")
def ollama_version():
    return {"version": "0.1.0-layla"}


@router.get("/api/tags")
def ollama_tags():
    """List Layla's 'models' (the base model + each aspect) in Ollama's tag shape."""
    names = ["layla"] + [f"layla-{a}" for a in _aspect_ids()]
    models = [
        {
            "name": n,
            "model": n,
            "modified_at": _now(),
            "size": 0,
            "digest": "",
            "details": {"family": "layla", "format": "gguf", "parameter_size": "", "quantization_level": ""},
        }
        for n in names
    ]
    return {"models": models}


@router.post("/api/chat")
async def ollama_chat(req: dict, request: Request):
    """Ollama /api/chat → OpenAI /v1/chat/completions → Ollama response."""
    from routers.openai_compat import v1_chat_completions

    body = req or {}
    oai = {
        "model": str(body.get("model") or "layla"),
        "messages": body.get("messages") or [],
        "stream": False,
        "workspace_root": body.get("workspace_root", "") or (body.get("options") or {}).get("workspace_root", ""),
    }
    _stop = (body.get("options") or {}).get("stop")   # Ollama nests stop under options; forward it to v1.
    if _stop:
        oai["stop"] = _stop
    resp = await v1_chat_completions(oai, request)
    content, d = _content_of(resp)
    if not d.get("choices") and d.get("error"):
        return JSONResponse({"error": (d.get("error") or {}).get("message", "error")}, status_code=400)
    return {
        "model": body.get("model") or "layla",
        "created_at": _now(),
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
    }


@router.post("/api/generate")
async def ollama_generate(req: dict, request: Request):
    """Ollama /api/generate (prompt string) → OpenAI chat → Ollama response."""
    from routers.openai_compat import v1_chat_completions

    body = req or {}
    prompt = str(body.get("prompt") or "")
    oai = {
        "model": str(body.get("model") or "layla"),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "workspace_root": body.get("workspace_root", "") or (body.get("options") or {}).get("workspace_root", ""),
    }
    _stop = (body.get("options") or {}).get("stop")   # Ollama nests stop under options; forward it to v1.
    if _stop:
        oai["stop"] = _stop
    resp = await v1_chat_completions(oai, request)
    content, d = _content_of(resp)
    if not d.get("choices") and d.get("error"):
        return JSONResponse({"error": (d.get("error") or {}).get("message", "error")}, status_code=400)
    return {
        "model": body.get("model") or "layla",
        "created_at": _now(),
        "response": content,
        "done": True,
        "done_reason": "stop",
    }
