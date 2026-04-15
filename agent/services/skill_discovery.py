"""Suggest skill packs / deps when tasks fail (stub for background review)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def record_skill_gap(goal: str, tool: str | None, err: str | None) -> None:
    """Log a lightweight gap signal (extend with SQLite telemetry later)."""
    logger.info("skill_gap: goal=%s tool=%s err=%s", (goal or "")[:120], tool, (err or "")[:120])


def suggest_packs_for_goal(goal: str) -> list[str]:
    """Heuristic pack ids for UX hints."""
    g = (goal or "").lower()
    out: list[str] = []
    if any(k in g for k in ("code", "refactor", "pytest", "git")):
        out.append("engineering")
    if any(k in g for k in ("paper", "arxiv", "citation", "research")):
        out.append("research")
    if any(k in g for k in ("translate", "language", "glossary")):
        out.append("translation")
    if any(k in g for k in ("dxf", "gcode", "cad", "cam")):
        out.append("cad_cam")
    return out
