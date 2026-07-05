"""Answer feedback router (BL-242) — 👍/👎 + corrections into the learning loop."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackBody(BaseModel):
    rating: str  # "up" | "down"
    goal: str = ""
    answer: str = ""
    correction: str = ""
    conversation_id: str = ""


@router.post("")
def record(body: FeedbackBody):
    from services.infrastructure.answer_feedback import record_feedback
    return record_feedback(
        body.rating, goal=body.goal, answer=body.answer,
        correction=body.correction, conversation_id=body.conversation_id,
    )


@router.get("/stats")
def stats():
    from services.infrastructure.answer_feedback import feedback_stats
    return feedback_stats()


@router.get("/hint")
def hint(max_chars: int = 400):
    from services.infrastructure.answer_feedback import feedback_hint_for_prompt
    return {"hint": feedback_hint_for_prompt(max_chars=max_chars)}
