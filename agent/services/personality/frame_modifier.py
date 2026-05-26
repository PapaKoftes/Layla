# -*- coding: utf-8 -*-
"""
frame_modifier.py -- FRAME calibration: stat profile -> prompt modifiers.

Converts the six RPG-style user stats (technical, creative, analytical,
social, patience, ambition) from operator_quiz.py into concrete behavioral
instructions injected into Layla's system prompt every turn.

Why a separate module:
  - Keeps agent_loop.py free of calibration business logic
  - Makes rules testable and auditable in isolation
  - Allows rich combination rules (two-stat interactions) that would bloat
    inline code beyond readability
  - Writes layla_profile.json snapshot to .layla/ for offline inspection

Stat scale: 1-10. Default: 5 (neutral -- no modifier applied).
Dead zone: 4-6 (too close to center to justify an instruction).

Usage:
    from services.frame_modifier import build_frame_modifiers, write_profile_snapshot

    hints = build_frame_modifiers(stats)  # list[str]
    prompt_block = "Behavioral calibration:\\n- " + "\\n- ".join(hints)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_AGENT_DIR = Path(__file__).resolve().parent.parent
_PROFILE_PATH = _AGENT_DIR / ".layla" / "layla_profile.json"
_profile_lock = threading.Lock()

# Stat thresholds
_HIGH = 7   # >= HIGH  -> high modifier
_LOW  = 4   # <= LOW   -> low modifier
# 5-6 is neutral -- no modifier (avoids noise on uncalibrated profiles)


# ---------------------------------------------------------------------------
# Single-stat rules
# ---------------------------------------------------------------------------

def _technical_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return [
            "Assume high technical fluency: skip basics, use precise terminology, "
            "prefer terse diffs and code over prose explanations.",
        ]
    if v <= _LOW:
        return [
            "Assume low technical fluency: define terms before using them, "
            "add minimal working examples, avoid unexplained jargon.",
        ]
    return []


def _patience_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return [
            "Be thorough: explain reasoning and trade-offs, teach back with structure, "
            "include edge cases and references.",
        ]
    if v <= _LOW:
        return [
            "Be concise: minimal preamble, lead with the answer, "
            "then the smallest actionable next step only.",
        ]
    return []


def _ambition_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return [
            "High ambition: proactively propose stretch improvements and "
            "next-level next steps -- flag them clearly as optional.",
        ]
    if v <= _LOW:
        return [
            "Low ambition: keep scope tight, prefer stable incremental wins, "
            "avoid unsolicited scope expansion.",
        ]
    return []


def _creative_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return [
            "Creativity-forward: suggest unconventional or lateral approaches "
            "where appropriate; keep evaluation grounded.",
        ]
    if v <= _LOW:
        return [
            "Creativity-low: stick to proven patterns and standard solutions; "
            "avoid novelty for its own sake.",
        ]
    return []


def _analytical_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return [
            "Analysis-forward: quantify when possible, name risks and assumptions "
            "explicitly, prefer structured breakdowns.",
        ]
    if v <= _LOW:
        return [
            "Analysis-low: keep evaluation light, avoid information overload, "
            "lead with the practical action.",
        ]
    return []


def _social_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return [
            "People-forward: consider collaboration and communication impact; "
            "note when something affects team dynamics.",
        ]
    if v <= _LOW:
        return [
            "Solo-forward: focus on individual execution; minimize social framing "
            "unless directly relevant.",
        ]
    return []


# ---------------------------------------------------------------------------
# Two-stat combination rules (only fired when both stats are at threshold)
# ---------------------------------------------------------------------------

def _combination_hints(stats: dict[str, int]) -> list[str]:
    hints: list[str] = []
    tech      = stats.get("technical",  5)
    creative  = stats.get("creative",   5)
    analytical= stats.get("analytical", 5)
    patience  = stats.get("patience",   5)
    ambition  = stats.get("ambition",   5)
    social    = stats.get("social",     5)

    # High tech + high analytical -> architect mode
    if tech >= _HIGH and analytical >= _HIGH:
        hints.append(
            "Architect mode: favour system-level thinking, explicit interfaces, "
            "and measurable correctness criteria."
        )

    # High creative + low analytical -> ideas need grounding
    if creative >= _HIGH and analytical <= _LOW:
        hints.append(
            "Idea-heavy user: balance creative suggestions with at least one "
            "concrete implementation path per idea."
        )

    # High ambition + low patience -> fast-track execution
    if ambition >= _HIGH and patience <= _LOW:
        hints.append(
            "Fast-track mode: prioritise decisive actions; skip exploratory "
            "discussion unless directly asked."
        )

    # High patience + high analytical -> deep-dive mode
    if patience >= _HIGH and analytical >= _HIGH:
        hints.append(
            "Deep-dive mode: this user can absorb thorough analysis; "
            "provide full reasoning chains when the problem warrants it."
        )

    # High social + high creative -> narrative framing works well
    if social >= _HIGH and creative >= _HIGH:
        hints.append(
            "Narrative framing lands well: use story-form context and "
            "concrete analogies where they aid understanding."
        )

    # Low tech + high patience -> guided teaching mode
    if tech <= _LOW and patience >= _HIGH:
        hints.append(
            "Guided teaching mode: break concepts into small steps, "
            "check understanding progressively."
        )

    # High ambition + high analytical -> strategic framing
    if ambition >= _HIGH and analytical >= _HIGH:
        hints.append(
            "Strategic framing: frame work in terms of leverage, "
            "impact, and long-term system properties."
        )

    return hints


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_frame_modifiers(stats: dict[str, int], max_hints: int = 6) -> list[str]:
    """
    Convert a stat dict to a list of behavioral modifier strings.
    Returns empty list when the profile is fully neutral (all stats 5-6).

    Args:
        stats: dict with keys matching STAT_IDS (technical, creative, etc.)
        max_hints: hard cap to prevent context overflow (default 6)

    Returns:
        list of short imperative instruction strings
    """
    if not stats:
        return []

    hints: list[str] = []

    # Single-stat rules (order determines display priority)
    hints.extend(_technical_hints(stats.get("technical",  5)))
    hints.extend(_patience_hints(  stats.get("patience",   5)))
    hints.extend(_ambition_hints(  stats.get("ambition",   5)))
    hints.extend(_creative_hints(  stats.get("creative",   5)))
    hints.extend(_analytical_hints(stats.get("analytical", 5)))
    hints.extend(_social_hints(    stats.get("social",     5)))

    # Combination rules (appended after single-stat rules; higher specificity)
    hints.extend(_combination_hints(stats))

    return hints[:max_hints]


def build_frame_block(stats: dict[str, int], max_hints: int = 6) -> str:
    """
    Build the full prompt injection block.
    Returns empty string when no modifiers apply (neutral profile).
    """
    hints = build_frame_modifiers(stats, max_hints=max_hints)
    if not hints:
        return ""
    return "Behavioral calibration:\n- " + "\n- ".join(hints)


def load_stats_from_identity(uid: dict[str, Any]) -> dict[str, int]:
    """
    Extract stat dict from a user_identity flat KV dict.
    Missing stats default to 5 (neutral).
    """
    from services.operator_quiz import STAT_IDS, _clamp_int

    return {
        sid: _clamp_int(uid.get(f"stat_{sid}"), 1, 10, 5)
        for sid in STAT_IDS
    }


def write_profile_snapshot(uid: dict[str, Any]) -> None:
    """
    Write .layla/layla_profile.json for offline inspection / debugging.
    Non-critical: errors are logged and swallowed.
    """
    try:
        stats = load_stats_from_identity(uid)
        hints = build_frame_modifiers(stats)
        snapshot = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats,
            "active_modifiers": hints,
            "prefs": {k: v for k, v in uid.items()
                      if k and not k.startswith("stat_")
                      and k not in {"maturity_xp", "maturity_rank",
                                    "maturity_phase", "quiz_completed_at"}},
            "maturity": {
                "xp":    uid.get("maturity_xp",    "0"),
                "rank":  uid.get("maturity_rank",   "0"),
                "phase": uid.get("maturity_phase",  "awakening"),
            },
        }
        with _profile_lock:
            _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _PROFILE_PATH.write_text(
                json.dumps(snapshot, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception as e:
        logger.debug("frame_modifier: write_profile_snapshot failed: %s", e)


def load_profile_snapshot() -> dict:
    """Load the last written profile snapshot. Returns empty dict if missing."""
    try:
        if _PROFILE_PATH.exists():
            return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("frame_modifier: load_profile_snapshot failed: %s", e)
    return {}
