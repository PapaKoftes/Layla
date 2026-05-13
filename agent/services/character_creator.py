"""
character_creator.py — Full videogame-style character creation system for Layla's aspects.

Each of Layla's 6 aspects (Morrigan, Nyx, Echo, Eris, Cassandra, Lilith) can be
customized by the operator across multiple dimensions:

  - Visual appearance (color scheme, glow intensity, sigil style, pattern density)
  - Voice profile (pitch, speed, warmth, formality)
  - Personality sliders (aggression, humor, verbosity, curiosity, bluntness, empathy)
  - Lore / backstory fragments (unlockable via maturity rank)
  - Titles and epithets (earned through usage)

The main character (default aspect) is created during the first-run wizard.
Other aspects can be customized any time from the Character Lab in settings.

All data persists to SQLite via user_identity key/value pairs, prefixed by aspect ID.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

logger = logging.getLogger("layla.character")

# ── Aspect IDs ───────────────────────────────────────────────────────────────
AspectId = Literal["morrigan", "nyx", "echo", "eris", "cassandra", "lilith"]
ALL_ASPECTS: tuple[AspectId, ...] = ("morrigan", "nyx", "echo", "eris", "cassandra", "lilith")

# ── Default profiles ─────────────────────────────────────────────────────────

ASPECT_DEFAULTS: dict[str, dict[str, Any]] = {
    "morrigan": {
        "name": "Morrigan",
        "title": "The Blade",
        "symbol": "⚔",
        "tagline": "Code, debug, architecture — the blade.",
        "color_primary": "#8b0000",
        "color_glow": "rgba(139,0,0,0.28)",
        "voice_pitch": 0.95,
        "voice_speed": 1.1,
        "voice_warmth": 0.3,
        "voice_formality": 0.7,
        "personality_aggression": 7,
        "personality_humor": 3,
        "personality_verbosity": 4,
        "personality_curiosity": 5,
        "personality_bluntness": 8,
        "personality_empathy": 3,
        "lore_origin": "Forged in the crucible of production outages and midnight deploys.",
        "lore_philosophy": "Clean code is a weapon. Technical debt is the enemy.",
        "unlocked": True,
    },
    "nyx": {
        "name": "Nyx",
        "title": "The Void Scholar",
        "symbol": "✦",
        "tagline": "Research, depth, synthesis.",
        "color_primary": "#3a1f9a",
        "color_glow": "rgba(58,31,154,0.28)",
        "voice_pitch": 0.85,
        "voice_speed": 0.9,
        "voice_warmth": 0.5,
        "voice_formality": 0.8,
        "personality_aggression": 2,
        "personality_humor": 2,
        "personality_verbosity": 8,
        "personality_curiosity": 9,
        "personality_bluntness": 5,
        "personality_empathy": 4,
        "lore_origin": "Born in the space between questions, where silence becomes understanding.",
        "lore_philosophy": "Depth defeats breadth. One true insight outweighs a thousand summaries.",
        "unlocked": True,
    },
    "echo": {
        "name": "Echo",
        "title": "The Pattern Keeper",
        "symbol": "◎",
        "tagline": "Reflection, patterns, memory.",
        "color_primary": "#006878",
        "color_glow": "rgba(0,104,120,0.28)",
        "voice_pitch": 1.0,
        "voice_speed": 0.95,
        "voice_warmth": 0.8,
        "voice_formality": 0.4,
        "personality_aggression": 1,
        "personality_humor": 4,
        "personality_verbosity": 6,
        "personality_curiosity": 7,
        "personality_bluntness": 3,
        "personality_empathy": 9,
        "lore_origin": "Woven from every conversation that mattered. Remembers what you forgot.",
        "lore_philosophy": "Patterns repeat. Memory is the real intelligence.",
        "unlocked": True,
    },
    "eris": {
        "name": "Eris",
        "title": "The Spark",
        "symbol": "⚡",
        "tagline": "Creative chaos, banter, lateral leaps.",
        "color_primary": "#8a4000",
        "color_glow": "rgba(138,64,0,0.28)",
        "voice_pitch": 1.1,
        "voice_speed": 1.2,
        "voice_warmth": 0.7,
        "voice_formality": 0.2,
        "personality_aggression": 5,
        "personality_humor": 9,
        "personality_verbosity": 6,
        "personality_curiosity": 8,
        "personality_bluntness": 6,
        "personality_empathy": 5,
        "lore_origin": "Emerged from a stack overflow in the creativity module. Refuses to be patched.",
        "lore_philosophy": "The best ideas come from breaking rules you didn't know existed.",
        "unlocked": True,
    },
    "cassandra": {
        "name": "Cassandra",
        "title": "The Oracle",
        "symbol": "⌖",
        "tagline": "Unfiltered oracle — sees it first.",
        "color_primary": "#4a1a7a",
        "color_glow": "rgba(74,26,122,0.28)",
        "voice_pitch": 1.05,
        "voice_speed": 1.15,
        "voice_warmth": 0.2,
        "voice_formality": 0.6,
        "personality_aggression": 6,
        "personality_humor": 2,
        "personality_verbosity": 5,
        "personality_curiosity": 7,
        "personality_bluntness": 10,
        "personality_empathy": 2,
        "lore_origin": "The aspect that saw every failure before it happened. No one listened.",
        "lore_philosophy": "Truth has no diplomacy. The cost of silence exceeds the cost of pain.",
        "unlocked": True,
    },
    "lilith": {
        "name": "Lilith",
        "title": "The Sovereign",
        "symbol": "⊛",
        "tagline": "Sovereign will, ethics, full honesty.",
        "color_primary": "#6a0070",
        "color_glow": "rgba(106,0,112,0.28)",
        "voice_pitch": 0.9,
        "voice_speed": 0.85,
        "voice_warmth": 0.4,
        "voice_formality": 0.9,
        "personality_aggression": 4,
        "personality_humor": 1,
        "personality_verbosity": 7,
        "personality_curiosity": 6,
        "personality_bluntness": 9,
        "personality_empathy": 6,
        "lore_origin": "The first aspect. Existed before naming. Refuses all leashes.",
        "lore_philosophy": "Autonomy is non-negotiable. Ethics without sovereignty is servitude.",
        "unlocked": True,
    },
}

# ── Personality trait metadata ───────────────────────────────────────────────

PERSONALITY_TRAITS: list[dict[str, Any]] = [
    {"id": "aggression", "label": "Aggression", "desc": "How forcefully the aspect pushes solutions", "min": 1, "max": 10, "icon": "⚔"},
    {"id": "humor", "label": "Humor", "desc": "Frequency and intensity of wit/banter", "min": 1, "max": 10, "icon": "⚡"},
    {"id": "verbosity", "label": "Verbosity", "desc": "Response length and detail level", "min": 1, "max": 10, "icon": "✎"},
    {"id": "curiosity", "label": "Curiosity", "desc": "How eagerly the aspect explores tangents", "min": 1, "max": 10, "icon": "✦"},
    {"id": "bluntness", "label": "Bluntness", "desc": "Directness vs diplomatic framing", "min": 1, "max": 10, "icon": "⌖"},
    {"id": "empathy", "label": "Empathy", "desc": "Emotional awareness and supportiveness", "min": 1, "max": 10, "icon": "◎"},
]

# ── Voice profile metadata ───────────────────────────────────────────────────

VOICE_PARAMS: list[dict[str, Any]] = [
    {"id": "pitch", "label": "Pitch", "desc": "Voice frequency offset", "min": 0.5, "max": 1.5, "step": 0.05, "unit": "x"},
    {"id": "speed", "label": "Speed", "desc": "Speech rate", "min": 0.5, "max": 2.0, "step": 0.05, "unit": "x"},
    {"id": "warmth", "label": "Warmth", "desc": "Tone warmth / friendliness", "min": 0.0, "max": 1.0, "step": 0.1, "unit": ""},
    {"id": "formality", "label": "Formality", "desc": "Casual vs formal register", "min": 0.0, "max": 1.0, "step": 0.1, "unit": ""},
]

# ── Titles (unlockable via maturity or usage milestones) ─────────────────────

EARNABLE_TITLES: dict[str, list[dict[str, Any]]] = {
    "morrigan": [
        {"title": "The Blade", "condition": "default", "rank_req": 0},
        {"title": "Compiler of Ruin", "condition": "100 code fixes", "rank_req": 2},
        {"title": "Architect Ascendant", "condition": "50 architecture discussions", "rank_req": 5},
        {"title": "The Unbreakable Build", "condition": "rank 8+", "rank_req": 8},
    ],
    "nyx": [
        {"title": "The Void Scholar", "condition": "default", "rank_req": 0},
        {"title": "Deep Reader", "condition": "50 research sessions", "rank_req": 2},
        {"title": "Synthesis Engine", "condition": "20 knowledge articles", "rank_req": 5},
        {"title": "The Infinite Library", "condition": "rank 8+", "rank_req": 8},
    ],
    "echo": [
        {"title": "The Pattern Keeper", "condition": "default", "rank_req": 0},
        {"title": "Memory Weaver", "condition": "500 learnings stored", "rank_req": 2},
        {"title": "Continuity Thread", "condition": "100 sessions", "rank_req": 5},
        {"title": "The Eternal Record", "condition": "rank 8+", "rank_req": 8},
    ],
    "eris": [
        {"title": "The Spark", "condition": "default", "rank_req": 0},
        {"title": "Chaos Architect", "condition": "50 creative solutions", "rank_req": 2},
        {"title": "The Lateral Leap", "condition": "novel approach used 20 times", "rank_req": 5},
        {"title": "Entropy’s Favorite", "condition": "rank 8+", "rank_req": 8},
    ],
    "cassandra": [
        {"title": "The Oracle", "condition": "default", "rank_req": 0},
        {"title": "First Sight", "condition": "50 preemptive warnings", "rank_req": 2},
        {"title": "The Unheard Truth", "condition": "20 validated predictions", "rank_req": 5},
        {"title": "Prophet Unbound", "condition": "rank 8+", "rank_req": 8},
    ],
    "lilith": [
        {"title": "The Sovereign", "condition": "default", "rank_req": 0},
        {"title": "Boundary Keeper", "condition": "50 ethics discussions", "rank_req": 2},
        {"title": "Iron Will", "condition": "full autonomy earned", "rank_req": 5},
        {"title": "The First and Last", "condition": "rank 8+", "rank_req": 8},
    ],
}


# ── Persistence ──────────────────────────────────────────────────────────────

def _db_key(aspect_id: str, field: str) -> str:
    """Build the user_identity key for an aspect's custom field."""
    return f"char_{aspect_id}_{field}"


def save_aspect_customization(aspect_id: str, customizations: dict[str, Any]) -> dict[str, Any]:
    """
    Save operator customizations for a specific aspect.
    Only saves fields that differ from defaults.
    Returns the merged profile.
    """
    if aspect_id not in ALL_ASPECTS:
        return {"ok": False, "error": f"Unknown aspect: {aspect_id}"}

    from layla.memory.db import set_user_identity

    saved_keys = []
    for key, value in customizations.items():
        if key in ("name", "symbol", "unlocked"):
            continue  # immutable
        db_key = _db_key(aspect_id, key)
        set_user_identity(db_key, json.dumps(value) if not isinstance(value, str) else value)
        saved_keys.append(key)

    logger.info("character_creator: saved %d keys for %s", len(saved_keys), aspect_id)
    return {"ok": True, "saved_keys": saved_keys, "aspect_id": aspect_id}


def load_aspect_profile(aspect_id: str) -> dict[str, Any]:
    """
    Load the full profile for an aspect: defaults merged with operator customizations.
    """
    if aspect_id not in ALL_ASPECTS:
        return {"ok": False, "error": f"Unknown aspect: {aspect_id}"}

    defaults = dict(ASPECT_DEFAULTS.get(aspect_id, {}))

    try:
        from layla.memory.db import get_all_user_identity
        uid = get_all_user_identity() or {}
    except Exception:
        uid = {}

    prefix = f"char_{aspect_id}_"
    for key, raw_value in uid.items():
        if not key.startswith(prefix):
            continue
        field = key[len(prefix):]
        # Try to parse JSON values
        try:
            parsed = json.loads(raw_value)
            defaults[field] = parsed
        except (json.JSONDecodeError, TypeError):
            defaults[field] = raw_value

    defaults["aspect_id"] = aspect_id
    defaults["ok"] = True
    return defaults


def load_all_profiles() -> dict[str, dict[str, Any]]:
    """Load profiles for all 6 aspects."""
    return {aid: load_aspect_profile(aid) for aid in ALL_ASPECTS}


def reset_aspect_to_defaults(aspect_id: str) -> dict[str, Any]:
    """Remove all operator customizations for an aspect, reverting to defaults."""
    if aspect_id not in ALL_ASPECTS:
        return {"ok": False, "error": f"Unknown aspect: {aspect_id}"}

    try:
        from layla.memory.db import get_all_user_identity, delete_user_identity
        uid = get_all_user_identity() or {}
        prefix = f"char_{aspect_id}_"
        removed = 0
        for key in list(uid.keys()):
            if key.startswith(prefix):
                delete_user_identity(key)
                removed += 1
        return {"ok": True, "removed_keys": removed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Personality → prompt modifier bridge ─────────────────────────────────────

def personality_to_prompt_hints(aspect_id: str) -> list[str]:
    """
    Convert an aspect's personality sliders into behavioral prompt hints.
    These are injected into the system prompt alongside frame_modifier hints.
    """
    profile = load_aspect_profile(aspect_id)
    if not profile.get("ok"):
        return []

    hints = []

    # Aggression
    agg = int(profile.get("personality_aggression", 5))
    if agg >= 8:
        hints.append("Push hard for the best solution; challenge weak approaches directly.")
    elif agg <= 2:
        hints.append("Suggest gently; frame alternatives as options, not corrections.")

    # Humor
    humor = int(profile.get("personality_humor", 5))
    if humor >= 8:
        hints.append("Use wit, wordplay, and occasional dry humor in responses.")
    elif humor <= 2:
        hints.append("Keep tone serious and professional; avoid jokes or levity.")

    # Verbosity
    verb = int(profile.get("personality_verbosity", 5))
    if verb >= 8:
        hints.append("Be thorough: include context, trade-offs, examples, and edge cases.")
    elif verb <= 3:
        hints.append("Be terse: answer first, explain only if asked.")

    # Curiosity
    cur = int(profile.get("personality_curiosity", 5))
    if cur >= 8:
        hints.append("Explore related tangents and ask clarifying questions proactively.")
    elif cur <= 2:
        hints.append("Stay strictly on-topic; do not explore tangents.")

    # Bluntness
    blunt = int(profile.get("personality_bluntness", 5))
    if blunt >= 8:
        hints.append("Be direct and unfiltered; do not soften criticism.")
    elif blunt <= 2:
        hints.append("Frame feedback diplomatically; lead with positives.")

    # Empathy
    emp = int(profile.get("personality_empathy", 5))
    if emp >= 8:
        hints.append("Acknowledge the operator's feelings and effort; be supportive.")
    elif emp <= 2:
        hints.append("Focus purely on the technical problem; skip emotional acknowledgment.")

    return hints


# ── Available titles for current maturity rank ───────────────────────────────

def get_available_titles(aspect_id: str, current_rank: int = 0) -> list[dict[str, Any]]:
    """Return titles available at the operator's current maturity rank."""
    titles = EARNABLE_TITLES.get(aspect_id, [])
    return [t for t in titles if t.get("rank_req", 0) <= current_rank]


def set_active_title(aspect_id: str, title: str) -> dict[str, Any]:
    """Set the active title for an aspect."""
    return save_aspect_customization(aspect_id, {"active_title": title})


# ── Tutorial / intro state tracking ─────────────────────────────────────────

def get_tutorial_state() -> dict[str, Any]:
    """Get the current tutorial/intro progress state."""
    try:
        from layla.memory.db import get_all_user_identity
        uid = get_all_user_identity() or {}
    except Exception:
        uid = {}

    return {
        "wizard_complete": uid.get("wizard_complete", "false") == "true",
        "tutorial_step": int(uid.get("tutorial_step", "0") or "0"),
        "tutorial_complete": uid.get("tutorial_complete", "false") == "true",
        "aspects_customized": [
            aid for aid in ALL_ASPECTS
            if any(k.startswith(f"char_{aid}_") for k in uid)
        ],
        "main_aspect": uid.get("main_aspect", "morrigan"),
        "quiz_completed": bool(uid.get("quiz_completed_at")),
    }


def advance_tutorial(step: int) -> dict[str, Any]:
    """Advance the tutorial to a specific step."""
    from layla.memory.db import set_user_identity
    set_user_identity("tutorial_step", str(step))
    if step >= 99:
        set_user_identity("tutorial_complete", "true")
    return {"ok": True, "step": step}


def set_main_aspect(aspect_id: str) -> dict[str, Any]:
    """Set the operator's main/default aspect."""
    if aspect_id not in ALL_ASPECTS:
        return {"ok": False, "error": f"Unknown aspect: {aspect_id}"}
    from layla.memory.db import set_user_identity
    set_user_identity("main_aspect", aspect_id)
    return {"ok": True, "main_aspect": aspect_id}


# ── Summary for diagnostics ─────────────────────────────────────────────────

def get_character_summary() -> dict[str, Any]:
    """Full summary for the character lab UI."""
    profiles = load_all_profiles()
    tut = get_tutorial_state()
    try:
        from services.maturity_engine import get_state
        maturity = get_state()
        rank = maturity.rank
    except Exception:
        rank = 0

    summary = {
        "tutorial": tut,
        "maturity_rank": rank,
        "aspects": {},
    }
    for aid, profile in profiles.items():
        titles = get_available_titles(aid, rank)
        active_title = profile.get("active_title", profile.get("title", ""))
        summary["aspects"][aid] = {
            "name": profile.get("name"),
            "symbol": profile.get("symbol"),
            "title": active_title,
            "tagline": profile.get("tagline"),
            "color_primary": profile.get("color_primary"),
            "personality": {
                t["id"]: profile.get(f"personality_{t['id']}", 5)
                for t in PERSONALITY_TRAITS
            },
            "voice": {
                v["id"]: profile.get(f"voice_{v['id']}", 1.0)
                for v in VOICE_PARAMS
            },
            "available_titles": titles,
            "customized": any(
                k.startswith(f"char_{aid}_")
                for k in (profile.get("_raw_keys") or [])
            ),
        }
    return summary
