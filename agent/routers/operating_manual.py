"""Personal operating manual router (BL-236)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/manual", tags=["manual"])


class NoteBody(BaseModel):
    category: str = "other"
    text: str


@router.get("")
def get_manual():
    from services.personality.operating_manual import build_manual, manual_markdown
    return {**build_manual(), "markdown": manual_markdown()}


@router.get("/summary")
def get_summary(max_chars: int = 600):
    from services.personality.operating_manual import manual_for_prompt
    return {"summary": manual_for_prompt(max_chars=max_chars)}


@router.get("/notes")
def list_notes():
    from services.personality.operating_manual import NOTE_CATEGORIES, list_notes as _list
    return {"notes": _list(), "categories": list(NOTE_CATEGORIES)}


@router.post("/notes")
def add_note(body: NoteBody):
    from services.personality.operating_manual import add_note as _add
    return _add(body.category, body.text)


@router.delete("/notes/{note_id}")
def delete_note(note_id: int):
    from services.personality.operating_manual import delete_note as _del
    return _del(note_id)
