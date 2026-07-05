"""Emotional presence router (BL-190) — inspect / nudge Layla's mood."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/mood", tags=["mood"])


class SignalBody(BaseModel):
    signal: str  # praise | correction | success | failure | greeting | ...


@router.get("")
def get_mood():
    from services.personality.emotional_presence import current_mood, mood_hint
    return {**current_mood(), "hint": mood_hint()}


@router.post("/signal")
def signal(body: SignalBody):
    from services.personality.emotional_presence import register_signal
    return register_signal(body.signal)


@router.post("/reset")
def reset():
    from services.personality.emotional_presence import reset as _reset
    _reset()
    return {"ok": True}
