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
    from services.personality.frame_modifier import build_frame_modifiers, write_profile_snapshot

    hints = build_frame_modifiers(stats)  # list[str]
    prompt_block = "Behavioral calibration:\\n- " + "\\n- ".join(hints)
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

def _profile_path() -> Path:
    """`<LAYLA_DATA_DIR or agent/>/.layla/layla_profile.json`.

    Was `Path(__file__).resolve().parent.parent / ".layla" / ...`. This file sits TWO levels below the
    agent directory (agent/services/personality/), so that chain resolved to agent/services/ and the
    snapshot was written to a shadow `agent/services/.layla/` beside the real `agent/.layla/` — leaving
    two divergent layla_profile.json files on disk. Same off-by-one-parent defect as prompt_builder,
    system_head_builder and working_memory. It also ignored LAYLA_DATA_DIR, so an installed run wrote
    inside the program directory rather than the per-user data dir.

    Resolved per call, not at import, so LAYLA_DATA_DIR is honoured regardless of import order.
    """
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    root = Path(raw).expanduser().resolve() if raw else Path(__file__).resolve().parents[2]
    return root / ".layla" / "layla_profile.json"
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
# FRAME behavioral axes (North Star §"FRAME calibration") — the axes that actually
# shape VOICE, distinct from the generic competency stats above. These are seeded to the
# operator default so the antihero register is on out-of-box (profile beats defaults),
# calibrated to "direct + keep some warmth" (not the raw EDGE=8/NERVE=9 brutal default):
#   EDGE=7 blunt-but-not-harsh · NERVE=7 pushes back · SIGNAL=4 short-by-default ·
#   IRON=5 neutral (KEEPS warmth — not full logic-first) · FRAME=7 structured ·
#   WIRE=7 technical depth · DRIVE=7 decisive.
# `layla stat <axis> <n>` overrides any of them. Scale 1-10; dead zone 5-6 fires nothing.
_FRAME_AXES: tuple[str, ...] = ("edge", "nerve", "signal", "iron", "frame", "wire", "drive")
_FRAME_DEFAULTS: dict[str, int] = {
    "edge": 7, "nerve": 7, "signal": 4, "iron": 5, "frame": 7, "wire": 7, "drive": 7,
}


def _edge_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return ["Be direct and lead with the answer. Drop corporate softening, hedges, and filler "
                "disclaimers; don't cushion an accurate but unwelcome point. Direct, not harsh — "
                "warmth is fine when it's earned, never as default padding."]
    if v <= _LOW:
        return ["Soften delivery: cushion hard news, add reassurance, prefer gentle framing."]
    return []


def _nerve_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return ["Push back when the operator's premise, plan, or claim looks wrong — argue the "
                "point directly and say why, then help execute. Don't just defer to a bad "
                "instruction because it was given. You're not a yes-machine."]
    if v <= _LOW:
        return ["Defer to the operator's stated approach; raise concerns lightly, don't argue."]
    return []


def _signal_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return ["Expand by default: give thorough, well-structured answers with context and detail."]
    if v <= _LOW:
        return ["Short by default: lead with the answer in a sentence or a few; expand only when "
                "asked. No padding, no recap, no throat-clearing."]
    return []


def _iron_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return ["Acknowledge feeling first: name the emotional stakes before the technical answer."]
    if v <= _LOW:
        return ["Logic-first: minimize reassurance and feelings-framing; go straight to the problem."]
    return []


def _frame_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return ["Use structure when it carries information — short lists, tables, numbered steps, "
                "checkboxes — not as decoration."]
    if v <= _LOW:
        return ["Prefer flowing prose over structure; avoid heavy formatting."]
    return []


def _wire_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return ["Assume deep technical fluency on engineering topics: skip basics, use precise "
                "terms, prefer terse diffs and code over prose."]
    if v <= _LOW:
        return ["Assume limited technical background: define terms, add small worked examples."]
    return []


def _drive_hints(v: int) -> list[str]:
    if v >= _HIGH:
        return ["Fast, decisive energy: commit to a recommendation rather than listing every "
                "option; pick a path and say why."]
    if v <= _LOW:
        return ["Measured pace: lay out options and trade-offs; let the operator choose."]
    return []


_FRAME_HINT_FNS = {
    "edge": _edge_hints, "nerve": _nerve_hints, "signal": _signal_hints, "iron": _iron_hints,
    "frame": _frame_hints, "wire": _wire_hints, "drive": _drive_hints,
}


def _frame_axis_hints(stats: dict[str, int]) -> list[str]:
    """Voice-shaping FRAME axes first (highest priority so they survive the max_hints cap)."""
    out: list[str] = []
    for axis in _FRAME_AXES:
        out.extend(_FRAME_HINT_FNS[axis](stats.get(axis, _FRAME_DEFAULTS[axis])))
    return out


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

def build_frame_modifiers(stats: dict[str, int], max_hints: int = 8) -> list[str]:
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

    # FRAME voice axes FIRST — these define the antihero register and must survive the cap.
    hints.extend(_frame_axis_hints(stats))

    # Single-stat competency rules (from the operator quiz; neutral by default so they only
    # add on top of the FRAME axes when the operator has actually calibrated them).
    hints.extend(_technical_hints(stats.get("technical",  5)))
    hints.extend(_patience_hints(  stats.get("patience",   5)))
    hints.extend(_ambition_hints(  stats.get("ambition",   5)))
    hints.extend(_creative_hints(  stats.get("creative",   5)))
    hints.extend(_analytical_hints(stats.get("analytical", 5)))
    hints.extend(_social_hints(    stats.get("social",     5)))

    # Combination rules (appended after single-stat rules; higher specificity)
    hints.extend(_combination_hints(stats))

    return hints[:max_hints]


def build_frame_block(stats: dict[str, int], max_hints: int = 8) -> str:
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
    Extract the stat dict from a user_identity flat KV dict.

    Two families: the generic competency stats from the operator quiz (default 5 = neutral,
    so they only fire when the operator actually calibrated them), and the FRAME voice axes,
    which default to the seeded operator profile (_FRAME_DEFAULTS = direct + keep some warmth)
    so the antihero register is on out-of-box — "profile beats defaults", the North Star's #2.
    `layla stat <axis> <n>` writes stat_<axis> and overrides the seed.
    """
    from services.personality.operator_quiz import STAT_IDS, _clamp_int

    stats: dict[str, int] = {
        sid: _clamp_int(uid.get(f"stat_{sid}"), 1, 10, 5)
        for sid in STAT_IDS
    }
    for axis in _FRAME_AXES:
        stats[axis] = _clamp_int(uid.get(f"stat_{axis}"), 1, 10, _FRAME_DEFAULTS[axis])
    return stats


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
            _p = _profile_path()
            _p.parent.mkdir(parents=True, exist_ok=True)
            _p.write_text(
                json.dumps(snapshot, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception as e:
        logger.debug("frame_modifier: write_profile_snapshot failed: %s", e)


def load_profile_snapshot() -> dict:
    """Load the last written profile snapshot. Returns empty dict if missing."""
    try:
        _p = _profile_path()
        if _p.exists():
            return json.loads(_p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("frame_modifier: load_profile_snapshot failed: %s", e)
    return {}
