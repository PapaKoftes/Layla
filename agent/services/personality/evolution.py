"""
personality evolution -- Gradual personality drift and communication style learning.

Layla's personality sliders (aggression, humor, verbosity, curiosity, bluntness,
empathy) are set initially via the character_creator, but they should evolve
slowly over time based on how the user actually interacts with each aspect.

This module:
  1. Tracks interaction patterns per aspect (type counts).
  2. Evolves personality sliders gradually based on usage patterns.
  3. Learns communication style preferences with exponential decay.
  4. Generates evolved personality hints for system prompt injection.

Persistence uses the user_identity key-value table with keys:
  - personality_drift_{aspect_id}     -> JSON dict of slider adjustments
  - communication_prefs_{aspect_id}   -> JSON dict of learned preferences
  - interaction_history_{aspect_id}   -> JSON dict of type counts
  - personality_last_evolved          -> ISO timestamp

Design constraints:
  - MUST NOT raise on failure (best-effort, like maturity_engine).
  - Drift is SLOW: max +/- 0.1 per 50 interactions, capped at +/- 0.5 per week.
  - Sliders are BOUNDED: never below 1 or above 10.
  - Singleton via get_personality_evolution() factory.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("layla.personality_evolution")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid interaction types
INTERACTION_TYPES = frozenset({
    "code_help", "emotional_support", "research", "creative", "debate", "casual",
})

# Valid communication preference types
PREFERENCE_TYPES = frozenset({
    "formality", "technical_depth", "emoji_use", "response_length",
})

# Personality traits that can drift
DRIFTABLE_TRAITS = ("aggression", "humor", "verbosity", "curiosity", "bluntness", "empathy")

# Drift rules: which interaction types push which trait, and direction
# Format: {interaction_type: [(trait, direction)]}
_DRIFT_RULES: dict[str, list[tuple[str, float]]] = {
    "code_help":          [("verbosity", +0.1), ("bluntness", +0.05)],
    "emotional_support":  [("empathy", +0.1), ("humor", +0.05)],
    "research":           [("verbosity", +0.1), ("curiosity", +0.1)],
    "creative":           [("humor", +0.1), ("curiosity", +0.05)],
    "debate":             [("bluntness", +0.1), ("aggression", +0.05)],
    "casual":             [("humor", +0.1), ("empathy", +0.05)],
}

# How many interactions before a single drift increment is applied
_DRIFT_INTERACTION_THRESHOLD = 50

# Maximum drift per trait per week
_MAX_WEEKLY_DRIFT = 0.5

# Absolute slider bounds
_SLIDER_MIN = 1.0
_SLIDER_MAX = 10.0

# Exponential decay factor for communication preferences (per interaction)
_PREF_DECAY = 0.98

# Max interactions to consider for preference averaging
_PREF_WINDOW = 100


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# PersonalityEvolution
# ---------------------------------------------------------------------------

class PersonalityEvolution:
    """Tracks and evolves personality sliders and communication preferences."""

    def record_interaction(
        self,
        aspect_id: str,
        interaction_type: str,
        context: dict | None = None,
    ) -> None:
        """Called after each conversation turn. Tracks patterns and triggers drift.

        Args:
            aspect_id: The aspect that handled this interaction.
            interaction_type: One of INTERACTION_TYPES.
            context: Optional dict with keys like tools_used, user_satisfaction, complexity.
        """
        if not aspect_id:
            return
        itype = (interaction_type or "casual").strip().lower()
        if itype not in INTERACTION_TYPES:
            itype = "casual"

        try:
            # Load current interaction history
            history = self._load_interaction_history(aspect_id)

            # Increment count
            history.setdefault("type_counts", {})
            history["type_counts"][itype] = int(history["type_counts"].get(itype, 0)) + 1
            history["total_interactions"] = int(history.get("total_interactions", 0)) + 1
            history["last_interaction_at"] = _utcnow_iso()

            # Track tools used (for interaction type inference)
            if context and isinstance(context, dict):
                tools = context.get("tools_used", [])
                if isinstance(tools, list) and tools:
                    history.setdefault("recent_tools", [])
                    history["recent_tools"] = (history["recent_tools"] + tools)[-50:]

            # Persist updated history
            self._save_interaction_history(aspect_id, history)

            # Check if drift should be applied
            total = history["total_interactions"]
            if total > 0 and total % _DRIFT_INTERACTION_THRESHOLD == 0:
                self._apply_drift(aspect_id, history)

        except Exception as e:
            logger.debug("record_interaction failed: %s", e)

    def learn_communication_preference(
        self,
        aspect_id: str,
        preference_type: str,
        value: float,
    ) -> None:
        """Learn user's preferred communication style.

        Args:
            aspect_id: The aspect to learn preferences for.
            preference_type: One of PREFERENCE_TYPES.
            value: Float value for the preference (0.0 - 1.0 typically).
        """
        if not aspect_id:
            return
        ptype = (preference_type or "").strip().lower()
        if ptype not in PREFERENCE_TYPES:
            return

        try:
            prefs = self._load_communication_prefs(aspect_id)

            # Exponential moving average with decay
            current = prefs.get(ptype, {})
            old_avg = float(current.get("value", value))
            count = int(current.get("count", 0))

            # Weighted: recent values matter more
            if count == 0:
                new_avg = value
            else:
                new_avg = old_avg * _PREF_DECAY + value * (1 - _PREF_DECAY)

            prefs[ptype] = {
                "value": round(new_avg, 4),
                "count": min(count + 1, _PREF_WINDOW),
                "last_updated": _utcnow_iso(),
            }

            self._save_communication_prefs(aspect_id, prefs)

        except Exception as e:
            logger.debug("learn_communication_preference failed: %s", e)

    def get_evolved_hints(self, aspect_id: str) -> str:
        """Returns evolved personality description for system prompt injection.

        Combines base personality (from character_creator) with drift adjustments
        and learned communication preferences.

        Returns natural language hints or empty string.
        """
        if not aspect_id:
            return ""

        try:
            drift = self._load_drift(aspect_id)
            prefs = self._load_communication_prefs(aspect_id)
            history = self._load_interaction_history(aspect_id)

            hints: list[str] = []

            # Drift hints
            if drift:
                for trait, adj in drift.items():
                    adj_f = float(adj)
                    if abs(adj_f) < 0.15:
                        continue  # too small to mention
                    direction = "higher" if adj_f > 0 else "lower"
                    hints.append(
                        f"Your {trait} has drifted {direction} ({adj_f:+.1f}) "
                        f"based on interaction patterns."
                    )

            # Communication preference hints
            pref_hints = []
            for ptype, pdata in prefs.items():
                if not isinstance(pdata, dict):
                    continue
                val = float(pdata.get("value", 0.5))
                count = int(pdata.get("count", 0))
                if count < 5:
                    continue  # not enough data yet

                if ptype == "formality":
                    if val > 0.7:
                        pref_hints.append("The user prefers formal, professional communication.")
                    elif val < 0.3:
                        pref_hints.append("The user prefers casual, relaxed communication.")
                elif ptype == "technical_depth":
                    if val > 0.7:
                        pref_hints.append("The user prefers detailed technical explanations.")
                    elif val < 0.3:
                        pref_hints.append("The user prefers high-level, non-technical summaries.")
                elif ptype == "response_length":
                    if val > 0.7:
                        pref_hints.append("The user prefers thorough, detailed responses.")
                    elif val < 0.3:
                        pref_hints.append("The user prefers concise, to-the-point responses.")

            if pref_hints:
                hints.extend(pref_hints)

            # Interaction pattern hints
            total = int(history.get("total_interactions", 0))
            if total >= 20:
                type_counts = history.get("type_counts", {})
                if type_counts:
                    # Find dominant interaction type
                    dominant = max(type_counts, key=lambda k: int(type_counts.get(k, 0)))
                    dominant_pct = int(type_counts[dominant]) / total * 100
                    if dominant_pct > 40:
                        type_labels = {
                            "code_help": "code assistance",
                            "emotional_support": "emotional support",
                            "research": "research and exploration",
                            "creative": "creative work",
                            "debate": "discussion and debate",
                            "casual": "casual conversation",
                        }
                        label = type_labels.get(dominant, dominant)
                        hints.append(
                            f"Most interactions with this aspect involve {label} "
                            f"({dominant_pct:.0f}% of {total} interactions)."
                        )

            if not hints:
                return ""

            return "Evolved personality observations:\n- " + "\n- ".join(hints)

        except Exception as e:
            logger.debug("get_evolved_hints failed: %s", e)
            return ""

    def get_drift_summary(self, aspect_id: str) -> dict[str, float]:
        """Return the current drift dict for an aspect (trait -> adjustment)."""
        try:
            return dict(self._load_drift(aspect_id))
        except Exception:
            return {}

    def get_interaction_stats(self, aspect_id: str) -> dict[str, Any]:
        """Return interaction history stats for an aspect."""
        try:
            return dict(self._load_interaction_history(aspect_id))
        except Exception:
            return {}

    # -----------------------------------------------------------------------
    # Internal: drift application
    # -----------------------------------------------------------------------

    def _apply_drift(self, aspect_id: str, history: dict) -> None:
        """Apply personality drift based on accumulated interaction patterns."""
        try:
            drift = self._load_drift(aspect_id)
            type_counts = history.get("type_counts", {})

            if not type_counts:
                return

            # Weekly drift cap check
            last_evolved = self._load_last_evolved()
            now = _utcnow()
            if last_evolved:
                try:
                    last_dt = datetime.fromisoformat(last_evolved)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    days_since = (now - last_dt).total_seconds() / 86400
                except Exception:
                    days_since = 999
            else:
                days_since = 999

            # Calculate week-based drift budget remaining
            # Each trait can drift at most _MAX_WEEKLY_DRIFT per 7 days
            week_fraction = min(1.0, days_since / 7.0) if days_since < 999 else 1.0

            # Phase 4C: Scale drift velocity by onboarding proactivity preference
            _drift_velocity = 1.0  # default
            try:
                from layla.memory.user_profile import get_user_identity as _pe_get_uid
                _pe_proactivity = _pe_get_uid("proactivity_level")
                if _pe_proactivity:
                    _pe_val = (_pe_proactivity.get("snapshot") or "").strip().lower() if isinstance(_pe_proactivity, dict) else ""
                    if _pe_val in ("minimal", "low"):
                        _drift_velocity = 0.5  # Slow evolution, stable personality
                    elif _pe_val in ("aggressive", "high"):
                        _drift_velocity = 1.5  # Faster personality development
                    # "moderate" stays at 1.0
            except Exception:
                pass
            max_drift_this_cycle = _MAX_WEEKLY_DRIFT * week_fraction * _drift_velocity

            # Find dominant interaction type
            total = sum(int(v) for v in type_counts.values())
            if total < _DRIFT_INTERACTION_THRESHOLD:
                return

            # Apply drift rules weighted by interaction frequency
            new_drift = dict(drift)
            for itype, rules in _DRIFT_RULES.items():
                count = int(type_counts.get(itype, 0))
                if count == 0:
                    continue
                weight = count / total  # fraction of interactions of this type

                for trait, direction in rules:
                    if trait not in DRIFTABLE_TRAITS:
                        continue
                    # Scale drift by interaction weight
                    increment = direction * weight
                    current = float(new_drift.get(trait, 0.0))
                    proposed = current + increment

                    # Cap to weekly maximum
                    if abs(proposed) > max_drift_this_cycle:
                        proposed = math.copysign(max_drift_this_cycle, proposed)

                    # Absolute cap at +/- MAX_WEEKLY_DRIFT (long-term bound)
                    proposed = max(-_MAX_WEEKLY_DRIFT * 4, min(_MAX_WEEKLY_DRIFT * 4, proposed))

                    new_drift[trait] = round(proposed, 3)

            self._save_drift(aspect_id, new_drift)
            self._save_last_evolved(_utcnow_iso())

        except Exception as e:
            logger.debug("_apply_drift failed: %s", e)

    # -----------------------------------------------------------------------
    # Internal: persistence helpers
    # -----------------------------------------------------------------------

    def _load_interaction_history(self, aspect_id: str) -> dict:
        return self._load_json_key(f"interaction_history_{aspect_id}")

    def _save_interaction_history(self, aspect_id: str, data: dict) -> None:
        self._save_json_key(f"interaction_history_{aspect_id}", data)

    def _load_drift(self, aspect_id: str) -> dict:
        return self._load_json_key(f"personality_drift_{aspect_id}")

    def _save_drift(self, aspect_id: str, data: dict) -> None:
        self._save_json_key(f"personality_drift_{aspect_id}", data)

    def _load_communication_prefs(self, aspect_id: str) -> dict:
        return self._load_json_key(f"communication_prefs_{aspect_id}")

    def _save_communication_prefs(self, aspect_id: str, data: dict) -> None:
        self._save_json_key(f"communication_prefs_{aspect_id}", data)

    def _load_last_evolved(self) -> str:
        try:
            from layla.memory.db import get_all_user_identity
            uid = get_all_user_identity() or {}
            return str(uid.get("personality_last_evolved", "") or "")
        except Exception:
            return ""

    def _save_last_evolved(self, iso_ts: str) -> None:
        try:
            from layla.memory.db import set_user_identity
            set_user_identity("personality_last_evolved", iso_ts)
        except Exception as e:
            logger.debug("_save_last_evolved failed: %s", e)

    def _load_json_key(self, key: str) -> dict:
        try:
            from layla.memory.db import get_all_user_identity
            uid = get_all_user_identity() or {}
            raw = uid.get(key, "")
            if raw and isinstance(raw, str):
                return json.loads(raw)
            return {}
        except (json.JSONDecodeError, Exception):
            return {}

    def _save_json_key(self, key: str, data: dict) -> None:
        try:
            from layla.memory.db import set_user_identity
            set_user_identity(key, json.dumps(data, separators=(",", ":")))
        except Exception as e:
            logger.debug("_save_json_key(%s) failed: %s", key, e)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: PersonalityEvolution | None = None


def get_personality_evolution() -> PersonalityEvolution:
    """Factory function returning the singleton PersonalityEvolution instance."""
    global _instance
    if _instance is None:
        _instance = PersonalityEvolution()
    return _instance


# ---------------------------------------------------------------------------
# Helper: infer interaction type from tools used
# ---------------------------------------------------------------------------

def infer_interaction_type(tools_used: list[str] | None) -> str:
    """Infer the interaction type from the list of tools used during a turn.

    Returns one of INTERACTION_TYPES.
    """
    if not tools_used:
        return "casual"

    tools = set(str(t).lower() for t in tools_used)

    code_tools = {
        "read_file", "write_file", "apply_patch", "replace_in_file",
        "grep_code", "code_lint", "code_format", "run_python", "run_tests",
        "shell", "git_status", "git_diff", "git_log", "git_commit",
        "git_add", "git_branch", "understand_file", "search_replace",
    }
    research_tools = {
        "web_search", "fetch_url", "study", "research",
        "ingest_chat_export_to_knowledge",
    }
    memory_tools = {
        "search_memories", "save_learning", "save_note",
        "save_aspect_memory",
    }
    creative_tools = {"brainstorm"}

    if tools & code_tools:
        return "code_help"
    if tools & research_tools:
        return "research"
    if tools & memory_tools:
        return "emotional_support"
    if tools & creative_tools:
        return "creative"

    return "casual"
