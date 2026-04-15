"""Aspect metadata API (Layla v3).

Read-only endpoint to surface the enriched personality character sheets to the UI.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import orchestrator

router = APIRouter(tags=["aspects"])


@router.get("/aspects/{aspect_id}")
def get_aspect(aspect_id: str):
    aid = (aspect_id or "").strip().lower()
    if not aid:
        return JSONResponse({"ok": False, "error": "aspect_id required"}, status_code=400)
    try:
        aspects = orchestrator._load_aspects()
        a = next((x for x in aspects if (x.get("id") or "").strip().lower() == aid), None)
        if not a:
            return JSONResponse({"ok": False, "error": "unknown_aspect"}, status_code=404)
        # Return a safe subset (no system prompt injection text needed in the UI).
        out = {
            "ok": True,
            "aspect": {
                "id": a.get("id"),
                "name": a.get("name"),
                "title": a.get("title"),
                "role": a.get("role"),
                "voice": a.get("voice"),
                "traits": a.get("traits"),
                "archetype": a.get("archetype"),
                "tropes": a.get("tropes"),
                "tropes_expanded": a.get("tropes_expanded"),
                "epitaph": a.get("epitaph"),
                "lore_seed": a.get("lore_seed"),
                "motifs": a.get("motifs"),
                "background_pattern": a.get("background_pattern"),
                "signature_phrases": a.get("signature_phrases"),
                "quirks_seed": a.get("quirks_seed"),
                "growth_arc": a.get("growth_arc"),
                "relationships": a.get("relationships"),
                "failure_mode": a.get("failure_mode"),
                "failure_mode_expanded": a.get("failure_mode_expanded"),
                "voice_evolution": a.get("voice_evolution"),
                "color": a.get("color"),
                "icon_svg": a.get("icon_svg"),
                "decision_bias": a.get("decision_bias"),
                "earned_title": a.get("earned_title"),
                "nsfw_capable": a.get("nsfw_capable"),
                "will_refuse": a.get("will_refuse"),
                "can_refuse": a.get("can_refuse"),
            },
        }
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

