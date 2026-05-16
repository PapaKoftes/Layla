# -*- coding: utf-8 -*-
"""
Multi-aspect deliberation API router.

Endpoints:
  POST /debate       - Run multi-aspect deliberation on a goal
  GET  /debate/modes - List available deliberation modes and descriptions
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from schemas.requests import DebateRequest

logger = logging.getLogger("layla")

router = APIRouter(tags=["debate"])


@router.post("/debate")
async def run_debate(req: DebateRequest):
    """
    Run multi-aspect deliberation on a goal.

    Body (JSON):
        goal:    str   - The question or task to deliberate on (required).
        mode:    str   - "auto", "solo", "debate", "council", "tribunal" (default "auto").
        aspects: list  - Explicit aspect IDs to use (optional; auto-selected when omitted).
        state:   dict  - Agent state context (optional, default {}).

    Returns:
        JSON with mode, final_response, aspect_responses, critiques,
        participating_aspects, synthesis_notes.
    """
    from fastapi.responses import JSONResponse as _JSONResp

    import runtime_safety
    from services.debate_engine import run_deliberation

    goal = req.goal
    mode = req.mode
    aspects = req.aspects
    state = req.state or {}

    if isinstance(aspects, list):
        aspects = [str(a).strip().lower() for a in aspects if a]
        if not aspects:
            aspects = None

    try:
        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}

    try:
        result = run_deliberation(
            goal=goal,
            state=state,
            cfg=cfg,
            mode=mode,
            aspects=aspects,
        )
        return {
            "ok": True,
            "mode": result.mode,
            "final_response": result.final_response,
            "aspect_responses": result.aspect_responses,
            "critiques": result.critiques,
            "participating_aspects": result.participating_aspects,
            "synthesis_notes": result.synthesis_notes,
        }
    except Exception as exc:
        logger.error("debate endpoint failed: %s", exc, exc_info=True)
        return _JSONResp({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/debate/modes")
def list_modes():
    """Return available deliberation modes and their descriptions."""
    from services.debate_engine import (
        ALL_ASPECT_IDS,
        ASPECT_DOMAINS,
        MODE_COUNCIL,
        MODE_DEBATE,
        MODE_SOLO,
        MODE_TRIBUNAL,
    )

    return {
        "ok": True,
        "modes": [
            {
                "id": MODE_SOLO,
                "label": "Solo",
                "aspects": 1,
                "description": "Single aspect responds (current default behavior).",
            },
            {
                "id": MODE_DEBATE,
                "label": "Debate",
                "aspects": 2,
                "description": "Two aspects argue opposing positions, then synthesize.",
            },
            {
                "id": MODE_COUNCIL,
                "label": "Council",
                "aspects": 3,
                "description": "Three aspects deliberate with weighted perspectives.",
            },
            {
                "id": MODE_TRIBUNAL,
                "label": "Tribunal",
                "aspects": 6,
                "description": "All six aspects weigh in (expensive, for critical decisions).",
            },
        ],
        "aspects": {
            aid: {"domains": domains}
            for aid, domains in ASPECT_DOMAINS.items()
        },
        "all_aspect_ids": ALL_ASPECT_IDS,
    }
