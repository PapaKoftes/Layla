"""Conversation CRUD and search."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

logger = logging.getLogger("layla")
router = APIRouter(tags=["conversations"])


@router.post("/conversations")
def create_conversation_api(req: dict = Body(default={})):
    """Create an empty conversation row (for New chat in UI)."""
    try:
        from layla.memory.db import create_conversation

        body = req if isinstance(req, dict) else {}
        cid = (body.get("conversation_id") or "").strip() or str(uuid.uuid4())
        title = (body.get("title") or "").strip()
        aspect_id = (body.get("aspect_id") or "").strip()
        row = create_conversation(cid, title=title, aspect_id=aspect_id)
        return JSONResponse({"ok": True, "conversation": row})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/conversations")
def list_conversations_api(limit: int = 200, tag: str = ""):
    try:
        from layla.memory.db import list_conversations_filtered

        return JSONResponse({"ok": True, "conversations": list_conversations_filtered(limit=limit, tag=tag or None)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/conversations/search")
def search_conversations_api(q: str = "", limit: int = 50, tag: str = ""):
    try:
        from layla.memory.db import search_conversations_filtered

        return JSONResponse({"ok": True, "conversations": search_conversations_filtered(q, limit=limit, tag=tag or None)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/conversations/{conversation_id}/tags")
def set_conversation_tags_api(conversation_id: str, req: dict):
    try:
        from layla.memory.db import set_conversation_tags

        tags = (req or {}).get("tags", "")
        ok = set_conversation_tags(conversation_id, tags)
        if not ok:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/conversations/tags/suggest")
def suggest_conversation_tags_api(prefix: str = "", limit: int = 20):
    try:
        from layla.memory.db import suggest_conversation_tags

        return JSONResponse({"ok": True, "tags": suggest_conversation_tags(prefix=prefix, limit=limit)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/conversations/{conversation_id}")
def get_conversation_api(conversation_id: str):
    try:
        from layla.memory.db import get_conversation

        row = get_conversation(conversation_id)
        if not row:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        return JSONResponse({"ok": True, "conversation": row})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages_api(conversation_id: str, limit: int = 300):
    try:
        from layla.memory.db import get_conversation_messages

        return JSONResponse({"ok": True, "messages": get_conversation_messages(conversation_id, limit=limit)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/conversations/{conversation_id}/rename")
def rename_conversation_api(conversation_id: str, req: dict):
    title = ((req or {}).get("title") or "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "title required"}, status_code=400)
    try:
        from layla.memory.db import rename_conversation

        ok = rename_conversation(conversation_id, title)
        if not ok:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.delete("/conversations/{conversation_id}")
def delete_conversation_api(conversation_id: str):
    try:
        from layla.memory.db import delete_conversation

        ok = delete_conversation(conversation_id)
        if not ok:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
