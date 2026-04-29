"""
routers/german.py — German language learning mode API (Item #10)

Endpoints:
  GET  /german/profile                  — User's CEFR profile
  POST /german/profile/level            — Set CEFR level
  POST /german/correct                  — Analyse and correct German text
  GET  /german/corrections              — Correction history
  GET  /german/calibrate/{level}        — Get calibration sentences
  POST /german/calibrate                — Submit calibration answers → recommended level
  GET  /german/flashcards/due           — Due flashcards
  GET  /german/flashcards/stats         — Deck stats
  POST /german/flashcards               — Add flashcard
  POST /german/flashcards/{id}/review   — Record review quality
  DELETE /german/flashcards/{id}        — Delete flashcard
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger("layla")
router = APIRouter(prefix="/german", tags=["german"])


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile")
async def get_profile(user_id: str = "default"):
    """Return the user's German learning profile."""
    try:
        from services.german_mode import get_profile as _get
        return {"ok": True, "profile": _get(user_id)}
    except Exception as e:
        logger.error("GET /german/profile failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/profile/level")
async def set_level(body: dict):
    """
    Set the CEFR level.
    Body: {level: "B1", user_id: "default"}
    """
    level = str(body.get("level", "B1")).strip()
    user_id = str(body.get("user_id", "default"))
    try:
        from services.german_mode import set_level as _set
        profile = _set(level, user_id)
        return {"ok": True, "profile": profile}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("POST /german/profile/level failed: %s", e)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Correction
# ---------------------------------------------------------------------------

@router.post("/correct")
async def correct_text(body: dict):
    """
    Analyse German text and return corrections.
    Body: {text: "...", user_id: "default"}
    """
    text = str(body.get("text", "")).strip()
    user_id = str(body.get("user_id", "default"))
    if not text:
        return {"ok": False, "error": "text is required"}
    try:
        from services.german_mode import correct_text as _correct
        return _correct(text, user_id)
    except Exception as e:
        logger.error("POST /german/correct failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.get("/corrections")
async def get_corrections(user_id: str = "default", limit: int = 20):
    """Return recent correction history."""
    try:
        from services.german_mode import get_corrections_history
        records = get_corrections_history(user_id, limit=min(limit, 200))
        return {"ok": True, "records": records, "total": len(records)}
    except Exception as e:
        logger.error("GET /german/corrections failed: %s", e)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

@router.get("/calibrate/{level}")
async def calibration_sentences(level: str):
    """Return example sentences for a given CEFR level."""
    try:
        from services.german_mode import get_calibration_sentences, CEFR_LEVELS
        lvl = level.upper()
        if lvl not in CEFR_LEVELS:
            return {"ok": False, "error": f"Unknown level: {level}. Use {CEFR_LEVELS}"}
        return {"ok": True, "level": lvl, "sentences": get_calibration_sentences(lvl)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/calibrate")
async def run_calibration(body: dict):
    """
    Submit calibration answers and get recommended CEFR level.
    Body: {answers: [{level: "B1", score: 4}, ...], user_id: "default"}
    """
    answers = body.get("answers", [])
    user_id = str(body.get("user_id", "default"))
    if not isinstance(answers, list) or not answers:
        return {"ok": False, "error": "answers must be a non-empty list"}
    try:
        from services.german_mode import calibrate_from_answers
        return calibrate_from_answers(answers, user_id)
    except Exception as e:
        logger.error("POST /german/calibrate failed: %s", e)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------

@router.get("/flashcards/due")
async def due_cards(user_id: str = "default", limit: int = 10):
    """Return flashcards due for review."""
    try:
        from services.german_mode import get_due_cards
        cards = get_due_cards(user_id, limit=min(limit, 50))
        return {"ok": True, "cards": cards, "total": len(cards)}
    except Exception as e:
        logger.error("GET /german/flashcards/due failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.get("/flashcards/stats")
async def flashcard_stats(user_id: str = "default"):
    """Return deck statistics."""
    try:
        from services.german_mode import get_flashcard_stats
        return {"ok": True, **get_flashcard_stats(user_id)}
    except Exception as e:
        logger.error("GET /german/flashcards/stats failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/flashcards")
async def add_flashcard(body: dict):
    """
    Add a new flashcard.
    Body: {front: "Haus", back: "house", example: "Das Haus ist groß.", tags: "nouns", user_id: "default"}
    """
    front = str(body.get("front", "")).strip()
    back = str(body.get("back", "")).strip()
    if not front or not back:
        return {"ok": False, "error": "front and back are required"}
    user_id = str(body.get("user_id", "default"))
    example = str(body.get("example", ""))
    tags = str(body.get("tags", ""))
    try:
        from services.german_mode import add_flashcard as _add
        return _add(front, back, example, tags, user_id)
    except Exception as e:
        logger.error("POST /german/flashcards failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/flashcards/{card_id}/review")
async def review_card(card_id: int, body: dict):
    """
    Record a review result.
    Body: {quality: 4, user_id: "default"}
    quality 0–5: 0-2=fail/again, 3=hard, 4=good, 5=easy.
    """
    quality = int(body.get("quality", 3))
    user_id = str(body.get("user_id", "default"))
    try:
        from services.german_mode import review_card as _review
        return _review(card_id, quality, user_id)
    except Exception as e:
        logger.error("POST /german/flashcards/%d/review failed: %s", card_id, e)
        return {"ok": False, "error": str(e)}


@router.delete("/flashcards/{card_id}")
async def delete_flashcard(card_id: int, user_id: str = "default"):
    """Delete a flashcard."""
    try:
        from services.german_mode import delete_flashcard as _del
        return _del(card_id, user_id)
    except Exception as e:
        logger.error("DELETE /german/flashcards/%d failed: %s", card_id, e)
        return {"ok": False, "error": str(e)}
