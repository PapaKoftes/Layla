"""Character Creator REST API — full CRUD for aspect profiles, titles, tutorial state."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("layla.character")

router = APIRouter(prefix="/character", tags=["character"])


# ── Request models ───────────────────────────────────────────────────────────

class AspectCustomization(BaseModel):
    """Fields the operator can tweak on an aspect."""
    title: str | None = None
    tagline: str | None = None
    color_primary: str | None = None
    color_glow: str | None = None
    voice_pitch: float | None = None
    voice_speed: float | None = None
    voice_warmth: float | None = None
    voice_formality: float | None = None
    personality_aggression: int | None = None
    personality_humor: int | None = None
    personality_verbosity: int | None = None
    personality_curiosity: int | None = None
    personality_bluntness: int | None = None
    personality_empathy: int | None = None
    active_title: str | None = None
    lore_custom_note: str | None = None


class TutorialAdvance(BaseModel):
    step: int = Field(ge=0, le=99)


class MainAspectSet(BaseModel):
    aspect_id: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/summary")
def character_summary():
    """Full character lab summary: all aspect profiles, tutorial state, maturity rank."""
    try:
        from services.character_creator import get_character_summary
        return get_character_summary()
    except Exception as e:
        logger.warning("character summary failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/aspects")
def list_aspects():
    """All 6 aspect profiles with operator customizations merged in."""
    try:
        from services.character_creator import load_all_profiles
        return load_all_profiles()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/aspects/{aspect_id}")
def get_aspect(aspect_id: str):
    """Single aspect profile."""
    from services.character_creator import ALL_ASPECTS, load_aspect_profile
    if aspect_id not in ALL_ASPECTS:
        return JSONResponse({"ok": False, "error": f"Unknown aspect: {aspect_id}"}, status_code=400)
    return load_aspect_profile(aspect_id)


@router.patch("/aspects/{aspect_id}")
def customize_aspect(aspect_id: str, body: AspectCustomization):
    """Save operator customizations for an aspect."""
    from services.character_creator import ALL_ASPECTS, save_aspect_customization
    if aspect_id not in ALL_ASPECTS:
        return JSONResponse({"ok": False, "error": f"Unknown aspect: {aspect_id}"}, status_code=400)
    # Only send non-None fields
    dump = body.model_dump if hasattr(body, "model_dump") else body.dict
    changes = {k: v for k, v in dump().items() if v is not None}
    if not changes:
        return {"ok": True, "saved_keys": [], "aspect_id": aspect_id}
    return save_aspect_customization(aspect_id, changes)


@router.post("/aspects/{aspect_id}/reset")
def reset_aspect(aspect_id: str):
    """Reset an aspect to factory defaults."""
    from services.character_creator import ALL_ASPECTS, reset_aspect_to_defaults
    if aspect_id not in ALL_ASPECTS:
        return JSONResponse({"ok": False, "error": f"Unknown aspect: {aspect_id}"}, status_code=400)
    return reset_aspect_to_defaults(aspect_id)


@router.get("/aspects/{aspect_id}/titles")
def get_titles(aspect_id: str):
    """Titles available at the current maturity rank."""
    from services.character_creator import ALL_ASPECTS, get_available_titles
    if aspect_id not in ALL_ASPECTS:
        return JSONResponse({"ok": False, "error": f"Unknown aspect: {aspect_id}"}, status_code=400)
    try:
        from services.maturity_engine import get_state
        rank = get_state().rank
    except Exception:
        rank = 0
    return {"aspect_id": aspect_id, "rank": rank, "titles": get_available_titles(aspect_id, rank)}


@router.post("/aspects/{aspect_id}/title")
def set_title(aspect_id: str, body: dict):
    """Set the active title for an aspect."""
    from services.character_creator import ALL_ASPECTS, set_active_title
    if aspect_id not in ALL_ASPECTS:
        return JSONResponse({"ok": False, "error": f"Unknown aspect: {aspect_id}"}, status_code=400)
    title = body.get("title", "")
    if not title:
        return JSONResponse({"ok": False, "error": "title required"}, status_code=400)
    return set_active_title(aspect_id, title)


@router.get("/aspects/{aspect_id}/prompt-hints")
def get_prompt_hints(aspect_id: str):
    """Personality slider values converted to behavioral prompt hints."""
    from services.character_creator import ALL_ASPECTS, personality_to_prompt_hints
    if aspect_id not in ALL_ASPECTS:
        return JSONResponse({"ok": False, "error": f"Unknown aspect: {aspect_id}"}, status_code=400)
    hints = personality_to_prompt_hints(aspect_id)
    return {"aspect_id": aspect_id, "hints": hints}


# ── Tutorial / Intro ─────────────────────────────────────────────────────────

@router.get("/tutorial")
def tutorial_state():
    """Current tutorial / intro progress."""
    from services.character_creator import get_tutorial_state
    return get_tutorial_state()


@router.post("/tutorial/advance")
def tutorial_advance(body: TutorialAdvance):
    """Advance the tutorial to a specific step."""
    from services.character_creator import advance_tutorial
    return advance_tutorial(body.step)


@router.post("/main-aspect")
def set_main(body: MainAspectSet):
    """Set the operator's main/default aspect."""
    from services.character_creator import set_main_aspect
    return set_main_aspect(body.aspect_id)


# ── Metadata ─────────────────────────────────────────────────────────────────

@router.get("/traits")
def personality_traits_metadata():
    """Metadata for personality trait sliders (label, range, icon)."""
    from services.character_creator import PERSONALITY_TRAITS
    return {"traits": PERSONALITY_TRAITS}


@router.get("/voice-params")
def voice_params_metadata():
    """Metadata for voice parameter sliders."""
    from services.character_creator import VOICE_PARAMS
    return {"params": VOICE_PARAMS}


@router.get("/earnable-titles")
def all_earnable_titles():
    """All earnable titles across all aspects (with unlock conditions)."""
    from services.character_creator import EARNABLE_TITLES
    return EARNABLE_TITLES
