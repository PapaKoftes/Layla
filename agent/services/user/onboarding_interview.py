"""Onboarding Interview — guided first-conversation for new Layla users.

When a user installs Layla for the first time, this module drives a
structured interview to:

1. Learn the user's name and preferences
2. Understand their work and pain points
3. Calibrate communication style (verbosity, directness, humour)
4. Let them shape Layla's personality
5. Establish data access boundaries
6. Name the relationship

Each stage produces structured data that's stored in the
``user_identity`` table for long-term companion behaviour.

Phase 4C of the distributed infrastructure plan.
"""
from __future__ import annotations

import enum
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("layla")


# ── Interview Stages ────────────────────────────────────────────────────

class InterviewStage(enum.Enum):
    """Ordered stages of the onboarding interview."""
    GREETING = "greeting"
    PURPOSE = "purpose"
    COMMUNICATION = "communication"
    PERSONALITY = "personality"
    DATA_CONSENT = "data_consent"
    NAMING = "naming"
    COMPLETE = "complete"

    @classmethod
    def ordered(cls) -> list[InterviewStage]:
        return [
            cls.GREETING,
            cls.PURPOSE,
            cls.COMMUNICATION,
            cls.PERSONALITY,
            cls.DATA_CONSENT,
            cls.NAMING,
        ]

    def next_stage(self) -> InterviewStage:
        stages = self.ordered()
        try:
            idx = stages.index(self)
            if idx + 1 < len(stages):
                return stages[idx + 1]
        except ValueError:
            pass
        return InterviewStage.COMPLETE

    @property
    def number(self) -> int:
        """1-based stage number (for progress display)."""
        try:
            return self.ordered().index(self) + 1
        except ValueError:
            return len(self.ordered()) + 1

    @property
    def total(self) -> int:
        return len(self.ordered())


# ── Stage definitions with prompts ───────────────────────────────────────

STAGE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "greeting": {
        "goal": "Introduce Layla, learn the user's name and language",
        "opener": (
            "Hello. I'm Layla — or I will be, once we get to know each other.\n\n"
            "Right now I'm a blank slate with opinions about ethics and boundaries, "
            "but no knowledge about you, your work, or what you need from me.\n\n"
            "I'd like to spend about 15 minutes learning who you are. "
            "After that, I'll start working — and I'll keep learning as we go.\n\n"
            "Can we start with the basics? What should I call you?"
        ),
        "data_keys": ["user_name", "preferred_name", "language_preference"],
        "followups": [
            "What language do you prefer I communicate in?",
            "Great to meet you, {preferred_name}. Let's move on.",
        ],
    },
    "purpose": {
        "goal": "Understand what they do and what they need help with",
        "opener": (
            "Now tell me a bit about yourself and your work.\n\n"
            "What do you do? What projects are you currently working on?\n"
            "And importantly — what takes up most of your time that you wish didn't?"
        ),
        "data_keys": ["profession", "current_projects", "pain_points", "tools_used"],
        "followups": [
            "What tools and software do you use daily?",
            "Is there a particular area where you most want my help?",
        ],
    },
    "communication": {
        "goal": "Calibrate how Layla talks to this user",
        "opener": (
            "Let me calibrate how I should communicate with you.\n\n"
            "Some people prefer brief, direct answers. Others like detailed "
            "explanations and context. Some want me to proactively suggest things, "
            "others prefer I wait to be asked.\n\n"
            "What's your style?"
        ),
        "data_keys": ["verbosity", "directness", "proactivity", "boundaries"],
        "followups": [
            "Should I be more analytical, creative, or balanced in my approach?",
            "Are there topics that are off-limits or sensitive?",
        ],
    },
    "personality": {
        "goal": "Let them shape who Layla becomes",
        "opener": (
            "I have different aspects to my personality — think of them like moods "
            "or facets that I lean into depending on what you need.\n\n"
            "I can be analytical and precise, warm and nurturing, playfully curious, "
            "or direct and no-nonsense. I can blend these too.\n\n"
            "What kind of personality would you like me to default to? "
            "And should I have a sense of humour? What kind?"
        ),
        "data_keys": ["aspect_weights", "humour_preference", "formality_level"],
        "followups": [
            "How formal or casual should I be? Think of a spectrum from "
            "'boardroom' to 'best friend'.",
        ],
    },
    "data_consent": {
        "goal": "Establish data access boundaries",
        "opener": (
            "I can learn from your documents, notes, code, and files — "
            "but only with your permission.\n\n"
            "Which folders would you like me to watch and learn from? "
            "Are there any folders I should never touch?\n\n"
            "I can also browse the web to research topics. Is that okay?"
        ),
        "data_keys": ["watch_folders", "exclude_folders", "web_access", "data_consent_level"],
        "followups": [
            "Should I automatically ingest new files when they appear, "
            "or ask you first?",
        ],
    },
    "naming": {
        "goal": "Name the relationship and finalise",
        "opener": (
            "Last thing. I go by Layla, but you can call me something else "
            "if you prefer.\n\n"
            "And how should I think of our relationship? I can be a professional "
            "assistant, a research partner, a learning companion, or something else "
            "entirely.\n\n"
            "What feels right?"
        ),
        "data_keys": ["layla_name", "relationship_type"],
        "followups": [],
    },
}


# ── Interview state ──────────────────────────────────────────────────────

@dataclass
class InterviewState:
    """Tracks the progress of an onboarding interview."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    stage: InterviewStage = InterviewStage.GREETING
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    is_complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage": self.stage.value,
            "stage_number": self.stage.number,
            "total_stages": self.stage.total,
            "progress_percent": round(
                (self.stage.number - 1) / self.stage.total * 100
            ) if not self.is_complete else 100,
            "responses": self.responses,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "is_complete": self.is_complete,
        }


# ── OnboardingInterview manager ──────────────────────────────────────────

class OnboardingInterview:
    """Manages the onboarding interview lifecycle.

    Usage:
    1. Check ``needs_onboarding()`` on first visit
    2. Call ``start()`` to begin
    3. Present each stage's opener + followups
    4. Call ``submit_response(stage, data)`` as user answers
    5. Call ``advance()`` to move to the next stage
    6. When complete, data is persisted to ``user_identity``
    """

    def __init__(self):
        self._state: InterviewState | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def needs_onboarding(self) -> bool:
        """Check if the user has completed onboarding."""
        try:
            from layla.memory.db_connection import _conn
            with _conn() as db:
                row = db.execute(
                    "SELECT snapshot FROM user_identity WHERE key = 'onboarding_complete'"
                ).fetchone()
                if row:
                    val = row["snapshot"] if isinstance(row, dict) else row[0]
                    return val != "true"
        except Exception:
            pass
        return True

    def start(self) -> InterviewState:
        """Start a new interview or resume an existing one."""
        if self._state and not self._state.is_complete:
            return self._state

        self._state = InterviewState()
        logger.info("Onboarding interview started (id=%s)", self._state.id)
        return self._state

    def get_state(self) -> InterviewState | None:
        """Get current interview state."""
        return self._state

    def get_current_stage_info(self) -> dict[str, Any]:
        """Get the info for the current stage (opener, goals, etc)."""
        if not self._state:
            return {"error": "no_active_interview"}

        stage_key = self._state.stage.value
        definition = STAGE_DEFINITIONS.get(stage_key, {})

        return {
            "stage": stage_key,
            "stage_number": self._state.stage.number,
            "total_stages": self._state.stage.total,
            "goal": definition.get("goal", ""),
            "opener": definition.get("opener", ""),
            "followups": definition.get("followups", []),
            "data_keys": definition.get("data_keys", []),
            "is_complete": self._state.is_complete,
        }

    def submit_response(self, stage: str, data: dict[str, Any]) -> dict[str, Any]:
        """Record the user's response for a stage.

        Parameters
        ----------
        stage : str
            The stage key (e.g. "greeting", "purpose").
        data : dict
            Key-value pairs of collected information.
        """
        if not self._state:
            return {"ok": False, "error": "no_active_interview"}

        self._state.responses[stage] = data

        # Store each piece immediately in user_identity
        for key, value in data.items():
            if value is not None:
                self._store_identity(key, value)

        return {
            "ok": True,
            "stage": stage,
            "stored_keys": list(data.keys()),
        }

    def advance(self) -> dict[str, Any]:
        """Move to the next interview stage.

        Returns the new stage info.
        """
        if not self._state:
            return {"ok": False, "error": "no_active_interview"}

        next_stage = self._state.stage.next_stage()
        if next_stage == InterviewStage.COMPLETE:
            return self.complete()

        self._state.stage = next_stage
        return {
            "ok": True,
            "stage": next_stage.value,
            "stage_info": self.get_current_stage_info(),
        }

    def complete(self) -> dict[str, Any]:
        """Mark the interview as complete and persist all data."""
        if not self._state:
            return {"ok": False, "error": "no_active_interview"}

        self._state.is_complete = True
        self._state.completed_at = datetime.now(timezone.utc).isoformat()
        self._state.stage = InterviewStage.COMPLETE

        # Mark onboarding as complete
        self._store_identity("onboarding_complete", "true")
        self._store_identity("onboarding_completed_at", self._state.completed_at)

        # Store a timeline event
        self._add_timeline_event(
            "onboarding_complete",
            "Onboarding interview completed — Layla has learned about the user.",
        )

        # Apply personality preferences
        self._apply_personality_prefs()

        logger.info("Onboarding interview completed (id=%s)", self._state.id)

        return {
            "ok": True,
            "is_complete": True,
            "summary": self._build_summary(),
        }

    def skip(self) -> dict[str, Any]:
        """Skip the interview (user doesn't want it)."""
        self._store_identity("onboarding_complete", "true")
        self._store_identity("onboarding_skipped", "true")
        if self._state:
            self._state.is_complete = True
            self._state.stage = InterviewStage.COMPLETE
        return {"ok": True, "skipped": True}

    # ── Internal persistence ─────────────────────────────────────────

    def _store_identity(self, key: str, value: Any) -> None:
        """Store a user identity key-value pair."""
        try:
            from layla.memory.db_connection import _conn
            from layla.time_utils import utcnow
            snapshot = json.dumps(value) if not isinstance(value, str) else value
            with _conn() as db:
                db.execute(
                    """INSERT OR REPLACE INTO user_identity (key, snapshot, updated_at)
                       VALUES (?, ?, ?)""",
                    (key, snapshot, utcnow().isoformat()),
                )
                db.commit()
        except Exception as e:
            logger.debug("Failed to store identity %s: %s", key, e)

    def _add_timeline_event(self, event_type: str, content: str) -> None:
        """Add a timeline event."""
        try:
            from layla.memory.db_connection import _conn
            from layla.time_utils import utcnow
            now = utcnow().isoformat()
            with _conn() as db:
                db.execute(
                    """INSERT INTO timeline_events
                       (event_type, content, timestamp, importance, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (event_type, content, now, 0.9, now),
                )
                db.commit()
        except Exception as e:
            logger.debug("Timeline event failed: %s", e)

    def _apply_personality_prefs(self) -> None:
        """Apply collected personality preferences to Layla's config."""
        if not self._state:
            return

        responses = self._state.responses
        personality = responses.get("personality", {})
        communication = responses.get("communication", {})

        # Map verbosity preference to response_length
        verbosity = communication.get("verbosity", "balanced")
        verbosity_map = {
            "brief": "short",
            "concise": "short",
            "balanced": "medium",
            "detailed": "long",
            "thorough": "long",
        }
        if verbosity in verbosity_map:
            self._store_identity("preferred_response_length", verbosity_map[verbosity])

        # Store formality level
        formality = personality.get("formality_level", "casual")
        self._store_identity("formality_level", formality)

        # Store humour preference
        humour = personality.get("humour_preference", "light")
        self._store_identity("humour_preference", humour)

        # Store proactivity preference
        proactivity = communication.get("proactivity", "moderate")
        self._store_identity("proactivity_level", proactivity)

        # Phase 4B: Set default aspect based on stated purpose
        purpose = responses.get("purpose", {})
        purpose_text = (purpose.get("profession", "") + " " + purpose.get("primary_use", "")).lower()
        if any(kw in purpose_text for kw in ("research", "academic", "science")):
            self._store_identity("default_aspect", "nyx")
        elif any(kw in purpose_text for kw in ("creative", "writing", "art", "design")):
            self._store_identity("default_aspect", "eris")
        elif any(kw in purpose_text for kw in ("safety", "security", "ethics")):
            self._store_identity("default_aspect", "lilith")
        elif any(kw in purpose_text for kw in ("software", "coding", "programming", "engineering")):
            self._store_identity("default_aspect", "cassandra")

        # Phase 3D: Set default watch directories based on purpose
        import json as _json
        if any(kw in purpose_text for kw in ("software", "coding", "programming")):
            self._store_identity("watch_folders", _json.dumps(["~/Documents", "~/Projects"]))
        elif any(kw in purpose_text for kw in ("research", "academic")):
            self._store_identity("watch_folders", _json.dumps(["~/Documents", "~/Downloads"]))
        else:
            self._store_identity("watch_folders", _json.dumps(["~/Documents"]))

        # Store work domains for system prompt injection (Phase 4A)
        if purpose_text.strip():
            self._store_identity("work_domains", purpose_text.strip()[:200])

    def _build_summary(self) -> dict[str, Any]:
        """Build a summary of what was learned."""
        if not self._state:
            return {}

        responses = self._state.responses
        summary = {
            "stages_completed": len(responses),
            "total_stages": InterviewStage.GREETING.total,
        }

        # Extract key facts
        greeting = responses.get("greeting", {})
        if "preferred_name" in greeting:
            summary["user_name"] = greeting["preferred_name"]

        purpose = responses.get("purpose", {})
        if "profession" in purpose:
            summary["profession"] = purpose["profession"]

        naming = responses.get("naming", {})
        if "relationship_type" in naming:
            summary["relationship"] = naming["relationship_type"]

        return summary


# ── Module-level singleton ───────────────────────────────────────────────

_interview: OnboardingInterview | None = None


def get_onboarding() -> OnboardingInterview:
    """Get or create the singleton OnboardingInterview."""
    global _interview
    if _interview is None:
        _interview = OnboardingInterview()
    return _interview


def needs_onboarding() -> bool:
    """Quick check if onboarding is needed."""
    return get_onboarding().needs_onboarding()
