from __future__ import annotations

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

router = APIRouter(tags=["journal"])


@router.get("/journal")
def journal_list(limit: int = 50, day: str = ""):
    try:
        from services.journal_engine import list_entries

        return JSONResponse(list_entries(limit=limit, day=day or ""))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/journal/daily")
def journal_daily(day: str = ""):
    try:
        from services.journal_engine import list_entries

        return JSONResponse(list_entries(limit=200, day=day or ""))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/journal")
def journal_add(req: dict = Body(default={})):
    try:
        from services.journal_engine import add_entry

        body = req if isinstance(req, dict) else {}
        entry_type = (body.get("entry_type") or "note").strip()
        content = (body.get("content") or "").strip()
        tags = body.get("tags") or ""
        project_id = (body.get("project_id") or "").strip()
        aspect_id = (body.get("aspect_id") or "").strip()
        conversation_id = (body.get("conversation_id") or "").strip()
        return JSONResponse(
            add_entry(
                entry_type,
                content,
                tags=tags,
                project_id=project_id,
                aspect_id=aspect_id,
                conversation_id=conversation_id,
            )
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

