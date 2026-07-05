"""Generalized multi-language tutor API (BL-220) — /language/*.

Language-parametrized surface over `services.infrastructure.language_tutor`: learn any language
(German + Italian + Spanish shipping). The legacy `/german/*` router stays as a German alias.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["language"])


@router.get("/language/languages")
def languages():
    from services.infrastructure.language_tutor import list_languages
    return {"ok": True, "languages": list_languages()}


@router.get("/language/{lang}/profile")
def profile(lang: str):
    from services.infrastructure.language_tutor import get_profile
    return get_profile(lang)


@router.post("/language/{lang}/level")
async def set_level_ep(lang: str, request: Request):
    from services.infrastructure.language_tutor import set_level
    body = await _json(request)
    return set_level(lang, str(body.get("level") or "B1"))


@router.post("/language/{lang}/correct")
async def correct_ep(lang: str, request: Request):
    from services.infrastructure.language_tutor import correct
    body = await _json(request)
    return correct(str(body.get("text") or ""), lang, level=body.get("level"))


@router.get("/language/{lang}/flashcards/due")
def flashcards_due(lang: str, limit: int = 20):
    from services.infrastructure.language_tutor import due_cards
    return due_cards(lang, limit=limit)


@router.get("/language/{lang}/flashcards/stats")
def flashcards_stats(lang: str):
    from services.infrastructure.language_tutor import stats
    return stats(lang)


@router.post("/language/{lang}/flashcards")
async def flashcards_add(lang: str, request: Request):
    from services.infrastructure.language_tutor import add_card
    body = await _json(request)
    return add_card(lang, str(body.get("front") or ""), str(body.get("back") or ""))


@router.post("/language/{lang}/flashcards/{card_id}/review")
async def flashcards_review(lang: str, card_id: int, request: Request):
    from services.infrastructure.language_tutor import review_card
    body = await _json(request)
    return review_card(card_id, int(body.get("quality", 3)))


@router.get("/language/{lang}/calibrate/{level}")
def calibrate_sentences(lang: str, level: str):
    from services.infrastructure.language_tutor import calibration_sentences
    return {"ok": True, "language": lang, "level": level.upper(), "sentences": calibration_sentences(lang, level)}


@router.post("/language/{lang}/calibrate")
async def calibrate_ep(lang: str, request: Request):
    from services.infrastructure.language_tutor import calibrate
    body = await _json(request)
    return calibrate(lang, body.get("answers") or [])


async def _json(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}
