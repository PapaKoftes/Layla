"""Maturity engine (Layla v3).

Stores maturity state in `user_identity`:
  - maturity_xp: int
  - maturity_rank: int
  - maturity_phase: str
  - maturity_last_event: str (short)
  - maturity_last_updated_at: ISO

This is designed to be safe to call from many code paths:
  - MUST NOT raise on failure
  - MUST keep writes small (user_identity snapshot max 4000 chars)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger("layla.maturity")

PhaseId = Literal["awakening", "attunement", "resonance", "sovereignty", "transcendence"]

# Ordered, low→high. Single source of truth for phase-name comparisons: gate sites MUST use
# the predicates below (is_early_phase / is_high_trust_phase / VALID_PHASES), NEVER hand-typed
# string literals — three features (proactive initiative, observation mode, voice evolution)
# silently died on typo'd names like "nascent"/"adept"/"veteran"/"transcendent" that are NOT
# valid phases. test_maturity_phase_gates.py asserts nobody reintroduces those.
PHASE_ORDER: tuple[str, ...] = ("awakening", "attunement", "resonance", "sovereignty", "transcendence")
VALID_PHASES: frozenset[str] = frozenset(PHASE_ORDER)
_EARLY_PHASES: frozenset[str] = frozenset(("awakening", "attunement"))
_HIGH_TRUST_PHASES: frozenset[str] = frozenset(("resonance", "sovereignty", "transcendence"))


def is_valid_phase(phase: str) -> bool:
    return str(phase or "").strip().lower() in VALID_PHASES


def is_early_phase(phase: str) -> bool:
    """First-contact phases — cautious, observation-mode behavior belongs here."""
    return str(phase or "").strip().lower() in _EARLY_PHASES


def is_high_trust_phase(phase: str) -> bool:
    """Later phases where proactive initiative / autonomous suggestions are unlocked."""
    return str(phase or "").strip().lower() in _HIGH_TRUST_PHASES


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        iv = int(float(v))
    except Exception:
        return default
    return max(lo, min(hi, iv))


# XP required to advance each rank (rank 0->1 uses index 0, etc.)
_XP_TO_NEXT: list[int] = [500, 1000, 2000, 3000, 5000, 8000, 12000, 18000, 26000, 36000, 50000, 70000, 100000]


def phase_for_rank(rank: int) -> PhaseId:
    r = max(0, int(rank))
    if r <= 2:
        return "awakening"
    if r <= 5:
        return "attunement"
    if r <= 8:
        return "resonance"
    if r <= 12:
        return "sovereignty"
    return "transcendence"


def xp_needed_for_next(rank: int) -> int | None:
    r = max(0, int(rank))
    if r >= len(_XP_TO_NEXT):
        return None
    return int(_XP_TO_NEXT[r])


@dataclass(frozen=True)
class MaturityState:
    xp: int
    rank: int
    phase: PhaseId


def get_state() -> MaturityState:
    """Read maturity from user_identity; provide defaults if missing."""
    try:
        from layla.memory.db import get_all_user_identity

        uid = get_all_user_identity() or {}
    except Exception:
        uid = {}
    xp = _clamp_int(uid.get("maturity_xp"), 0, 2_000_000_000, 0)
    rank = _clamp_int(uid.get("maturity_rank"), 0, 100_000, 0)
    phase_raw = str(uid.get("maturity_phase") or "").strip().lower()
    phase: PhaseId = phase_for_rank(rank)
    if phase_raw in ("awakening", "attunement", "resonance", "sovereignty", "transcendence"):
        phase = phase_raw  # type: ignore[assignment]
    return MaturityState(xp=xp, rank=rank, phase=phase)


def get_progress_metrics() -> dict[str, int]:
    """
    Small deterministic counters used for milestones. Best-effort: never raise.
    """
    metrics: dict[str, int] = {
        "conversations": 0,
        "messages": 0,
        "learnings": 0,
        "successful_actions": 0,
        "approvals_ok": 0,
        "study_sessions": 0,
        "research_completed": 0,
        "distinct_aspects_used": 0,
    }
    try:
        from layla.memory.db import _conn, count_learnings, migrate

        migrate()
        metrics["learnings"] = int(count_learnings() or 0)
        with _conn() as db:
            try:
                row = db.execute("SELECT COUNT(*) as cnt FROM conversations").fetchone()
                metrics["conversations"] = int(row["cnt"] if row else 0)
            except Exception:
                pass
            try:
                row = db.execute("SELECT COUNT(*) as cnt FROM conversation_messages").fetchone()
                metrics["messages"] = int(row["cnt"] if row else 0)
            except Exception:
                pass
            try:
                row = db.execute("SELECT COUNT(*) as cnt FROM audit WHERE result_ok=1").fetchone()
                metrics["successful_actions"] = int(row["cnt"] if row else 0)
            except Exception:
                pass
            try:
                row = db.execute(
                    "SELECT COUNT(*) as cnt FROM audit WHERE tool='approve' AND result_ok=1"
                ).fetchone()
                metrics["approvals_ok"] = int(row["cnt"] if row else 0)
            except Exception:
                # approvals may log different tool names; keep best-effort.
                pass
            try:
                row = db.execute("SELECT COUNT(*) as cnt FROM audit WHERE tool='study'").fetchone()
                metrics["study_sessions"] = int(row["cnt"] if row else 0)
            except Exception:
                pass
            try:
                row = db.execute("SELECT COUNT(*) as cnt FROM missions WHERE status='done'").fetchone()
                metrics["research_completed"] = int(row["cnt"] if row else 0)
            except Exception:
                pass
            try:
                row = db.execute(
                    "SELECT COUNT(DISTINCT COALESCE(NULLIF(aspect_id,''),'morrigan')) as cnt FROM conversation_messages"
                ).fetchone()
                metrics["distinct_aspects_used"] = int(row["cnt"] if row else 0)
            except Exception:
                pass
    except Exception:
        return metrics
    return metrics


PHASE_MILESTONES: dict[PhaseId, list[dict[str, Any]]] = {
    "awakening": [
        {"id": "ten_conversations", "label": "Hold 10 conversations", "metric": "conversations", "target": 10},
        {"id": "five_learnings", "label": "Save 5 learnings/memories", "metric": "learnings", "target": 5},
        {"id": "first_approval", "label": "Approve 1 action", "metric": "approvals_ok", "target": 1},
    ],
    "attunement": [
        {"id": "fifty_learnings", "label": "Reach 50 learnings", "metric": "learnings", "target": 50},
        {"id": "three_aspects", "label": "Use 3 different voices (aspects)", "metric": "distinct_aspects_used", "target": 3},
        {"id": "quiz_done", "label": "Finish operator character creation", "metric": "quiz_completed", "target": 1},
    ],
    "resonance": [
        {"id": "two_hundred_success", "label": "200 successful actions", "metric": "successful_actions", "target": 200},
        {"id": "ten_study_sessions", "label": "10 study sessions", "metric": "study_sessions", "target": 10},
        {"id": "first_research", "label": "Complete 1 research mission", "metric": "research_completed", "target": 1},
    ],
    "sovereignty": [
        {"id": "five_hundred_learnings", "label": "Reach 500 learnings", "metric": "learnings", "target": 500},
        {"id": "five_approvals", "label": "Approve 5 actions", "metric": "approvals_ok", "target": 5},
        {"id": "one_thousand_success", "label": "1000 successful actions", "metric": "successful_actions", "target": 1000},
    ],
    "transcendence": [
        {"id": "one_thousand_messages", "label": "1000 messages exchanged", "metric": "messages", "target": 1000},
        {"id": "all_aspects", "label": "Use all 6 voices", "metric": "distinct_aspects_used", "target": 6},
        {"id": "two_thousand_success", "label": "2000 successful actions", "metric": "successful_actions", "target": 2000},
    ],
}


def get_milestones_status(phase: PhaseId | None = None) -> list[dict[str, Any]]:
    """
    Returns milestone statuses for the given phase (or current phase).
    Each item: {id,label,completed,progress,metric,target,value}.
    """
    st = get_state()
    ph: PhaseId = phase or st.phase
    metrics = get_progress_metrics()
    out: list[dict[str, Any]] = []
    # quiz_completed is stored as quiz_completed_at in user_identity when the quiz finalizes.
    quiz_done = 0
    try:
        from layla.memory.db import get_user_identity

        q = get_user_identity("quiz_completed_at") or {}
        quiz_done = 1 if str((q.get("snapshot") if isinstance(q, dict) else q) or "").strip() else 0
    except Exception:
        quiz_done = 0
    metrics_with_flags = dict(metrics)
    metrics_with_flags["quiz_completed"] = int(quiz_done)

    for m in PHASE_MILESTONES.get(ph, []):
        mid = str(m.get("id") or "")
        label = str(m.get("label") or mid)
        metric = str(m.get("metric") or "")
        target = _clamp_int(m.get("target"), 0, 2_000_000_000, 0)
        val = _clamp_int(metrics_with_flags.get(metric), 0, 2_000_000_000, 0)
        completed = bool(target == 0 or val >= target)
        progress = f"{min(val, target)}/{target}" if target > 0 else str(val)
        out.append(
            {
                "id": mid,
                "label": label,
                "metric": metric,
                "target": int(target),
                "value": int(val),
                "completed": completed,
                "progress": progress,
            }
        )
    return out


def _maturity_enabled(cfg: dict | None = None) -> bool:
    if cfg is None:
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    return bool(cfg.get("maturity_enabled", True))


def get_trust_tier(cfg: dict | None = None) -> int:
    """
    Lightweight autonomy trust tier (0-3). Default is conservative:
    - 0: suggestions only
    - 1: inline initiative allowed
    - 2: background task proposals / project proposals allowed
    - 3: operator-granted override only (never automatic)
    """
    if cfg is None:
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    if not bool(cfg.get("autonomy_trust_tiers_enabled", False)):
        return 0

    # Explicit operator override (config or user_identity).
    try:
        ov = cfg.get("trust_tier_override")
        if ov is None:
            from layla.memory.db import get_user_identity

            row = get_user_identity("trust_tier_override") or {}
            ov = row.get("snapshot") if isinstance(row, dict) else None
        if ov is not None:
            v = _clamp_int(ov, 0, 3, 0)
            return v
    except Exception:
        pass

    st = get_state()
    r = int(st.rank)
    if r >= 6:
        return 2
    if r >= 2:
        return 1
    return 0


def _persist_state(state: MaturityState, *, last_event: str = "") -> None:
    try:
        from layla.memory.db import set_user_identity

        set_user_identity("maturity_xp", str(int(state.xp)))
        set_user_identity("maturity_rank", str(int(state.rank)))
        set_user_identity("maturity_phase", str(state.phase))
        if last_event:
            set_user_identity("maturity_last_event", (last_event or "").strip()[:240])
        set_user_identity("maturity_last_updated_at", _utcnow_iso())
    except Exception:
        # never raise from persistence
        return


def award_xp(amount: int, *, reason: str = "", cfg: dict | None = None) -> dict[str, Any]:
    """Award XP and rank up if thresholds crossed. Returns a small event dict."""
    if not _maturity_enabled(cfg):
        return {"ok": True, "enabled": False}

    amt = _clamp_int(amount, 0, 1_000_000, 0)
    if amt <= 0:
        return {"ok": True, "enabled": True, "changed": False}

    before = get_state()
    xp = before.xp + amt
    rank = before.rank
    ranked_up = False

    # Rank up as long as we have enough XP for the next rank.
    while True:
        need = xp_needed_for_next(rank)
        if need is None:
            break
        if xp < need:
            break
        xp -= need
        rank += 1
        ranked_up = True

    after = MaturityState(xp=int(xp), rank=int(rank), phase=phase_for_rank(rank))
    _persist_state(after, last_event=reason or "xp_award")

    event: dict[str, Any] = {
        "ok": True,
        "enabled": True,
        "changed": True,
        "reason": (reason or "").strip()[:240],
        "awarded_xp": int(amt),
        "state_before": {"xp": before.xp, "rank": before.rank, "phase": before.phase},
        "state_after": {"xp": after.xp, "rank": after.rank, "phase": after.phase},
        "ranked_up": bool(ranked_up),
    }
    if ranked_up:
        event["rank_up"] = {"new_rank": after.rank, "new_phase": after.phase}
    return event


def seed_if_missing() -> None:
    """Ensure maturity keys exist (idempotent)."""
    if not _maturity_enabled(None):
        return
    try:
        from layla.memory.db import get_all_user_identity

        uid = get_all_user_identity() or {}
    except Exception:
        uid = {}
    if uid.get("maturity_xp") or uid.get("maturity_rank") or uid.get("maturity_phase"):
        return
    _persist_state(MaturityState(xp=0, rank=0, phase="awakening"), last_event="seed")


# ---------------------------------------------------------------------------
# Unlock system: abilities/features gated by rank
# ---------------------------------------------------------------------------

# Unlocks by rank threshold. Each entry: (min_rank, type, name, description, config_keys).
#
# HONESTY CONTRACT: every name here is concatenated into the system prompt by
# get_unlocks_text() and asserted aloud by get_growth_narrative() ("I recently unlocked X").
# That makes this table a capability source competing with .identity/capabilities.md, so it
# may only name things that actually exist. Each entry MUST carry at least one config key
# that some code path outside runtime_safety/config_schema actually READS.
#
# Removed (named a capability with no implementation anywhere in the repo):
#   rank 7  "Cross-aspect synthesis" — no config key, no code path.
#   rank 12 "Teacher mode"           — no config key, no code path.
#   rank 3  "Research autonomy"      — mapped to autonomous_research_mode, which is written
#                                      (runtime_safety.py:471/:914, runtime_config.example.json)
#                                      and read NOWHERE. An inert key is not a capability.
# Do not re-add a row here without wiring the behaviour first.
_RANK_UNLOCKS: list[tuple[int, str, str, str, tuple[str, ...]]] = [
    (1,  "ability", "Proactive suggestions",     "Layla can initiate topics and suggest next steps.",
     ("inline_initiative_enabled", "initiative_engine_enabled")),
    (5,  "ability", "Multi-step planning",        "Can execute complex multi-step plans autonomously.",
     ("autonomous_mode",)),
    (10, "feature", "Full autonomy mode",         "Minimal supervision needed for routine tasks.",
     ("initiative_project_proposals_enabled", "autonomy_optimizer_enabled")),
]


def check_unlocks(state: dict | None = None) -> list[dict[str, Any]]:
    """Check which abilities/features are unlocked based on current rank.

    Args:
        state: Optional dict with 'rank' key. If None, reads from DB.

    Returns:
        List of {type, name, description, rank_required, enabled} for every rank-earned
        capability. `enabled` reports whether it is ALSO switched on in config — the growth
        dashboard shows everything earned, while the prompt path (get_unlocks_text) names only
        the enabled ones.
    """
    try:
        if state and isinstance(state, dict) and "rank" in state:
            rank = _clamp_int(state["rank"], 0, 100_000, 0)
        else:
            ms = get_state()
            rank = ms.rank

        cfg: dict = {}
        try:
            import runtime_safety
            cfg = runtime_safety.load_config() or {}
        except Exception as e:
            logger.debug("check_unlocks config load failed: %s", e)

        unlocked = []
        for min_rank, utype, name, desc, keys in _RANK_UNLOCKS:
            if rank >= min_rank:
                # Rank is only half the story. The maturity gate DISABLES a capability below
                # its rank but never re-enables it above, so past the threshold the feature is
                # whatever setup_profiles/settings left it as. "Earned" therefore does not mean
                # "active", and the prompt path must not conflate them.
                unlocked.append({
                    "type": utype,
                    "name": name,
                    "description": desc,
                    "rank_required": min_rank,
                    "enabled": (not keys) or any(bool(cfg.get(k)) for k in keys),
                })
        return unlocked
    except Exception as e:
        logger.debug("check_unlocks failed: %s", e)
        return []


def all_unlocks(rank: int = 0) -> list[dict[str, Any]]:
    """The FULL unlock ladder (earned and not-yet-earned), for the growth dashboard.

    Exists so the UI stops carrying its own hardcoded copy of the ladder: growth.js used to
    duplicate the names and ranks, which meant trimming a fake capability from the table left
    the user still staring at "Teacher mode — Rank 12" in the locked-preview list.
    """
    out: list[dict[str, Any]] = []
    for min_rank, utype, name, desc, _keys in _RANK_UNLOCKS:
        out.append({
            "type": utype,
            "name": name,
            "description": desc,
            "rank_required": min_rank,
            "earned": int(rank) >= min_rank,
        })
    return out


def get_unlocks_text(state: dict | None = None) -> str:
    """Return a formatted string of currently ACTIVE unlocks for prompt injection.

    Only capabilities that are both rank-earned and switched on are named. Telling the model
    it has an ability the operator has turned off in setup_profiles produces exactly the kind
    of confident false claim .identity/capabilities.md exists to prevent — and unlike that
    manifest, this string reaches the prompt on every turn.
    """
    active = [u["name"] for u in check_unlocks(state) if u.get("enabled")]
    if not active:
        return ""
    return "Your current capabilities: " + ", ".join(active)


# ---------------------------------------------------------------------------
# Relationship depth tracking
# ---------------------------------------------------------------------------

def _load_relationship() -> dict[str, Any]:
    """Load relationship tracking data from user_identity."""
    try:
        from layla.memory.db import get_all_user_identity
        uid = get_all_user_identity() or {}
        raw = uid.get("maturity_relationship", "")
        if raw and isinstance(raw, str):
            return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        pass
    return {}


def _save_relationship(data: dict[str, Any]) -> None:
    """Persist relationship tracking data to user_identity."""
    try:
        from layla.memory.db import set_user_identity
        set_user_identity("maturity_relationship", json.dumps(data, separators=(",", ":")))
    except Exception as e:
        logger.debug("_save_relationship failed: %s", e)


def get_relationship_state() -> dict[str, Any]:
    """Return the current relationship tracking state with defaults."""
    rel = _load_relationship()
    now = _utcnow_iso()
    return {
        "first_interaction": rel.get("first_interaction", now),
        "total_days_active": int(rel.get("total_days_active", 0)),
        "longest_streak_days": int(rel.get("longest_streak_days", 0)),
        "current_streak_days": int(rel.get("current_streak_days", 0)),
        "trust_events": int(rel.get("trust_events", 0)),
        "correction_events": int(rel.get("correction_events", 0)),
        "shared_achievements": list(rel.get("shared_achievements", [])),
        "last_active_date": rel.get("last_active_date", ""),
    }


def record_relationship_event(event_type: str, detail: str = "") -> None:
    """Record a relationship event (trust, correction, achievement, daily activity).

    Args:
        event_type: One of "trust", "correction", "achievement", "active".
        detail: Optional detail string (for achievements).
    """
    try:
        rel = get_relationship_state()
        now = _utcnow_iso()
        today = now[:10]  # YYYY-MM-DD

        if event_type == "trust":
            rel["trust_events"] = int(rel.get("trust_events", 0)) + 1
        elif event_type == "correction":
            rel["correction_events"] = int(rel.get("correction_events", 0)) + 1
        elif event_type == "achievement" and detail:
            achievements = list(rel.get("shared_achievements", []))
            achievements.append({"text": detail[:200], "date": today})
            rel["shared_achievements"] = achievements[-50:]  # keep last 50

        # Daily activity tracking (streak and active days)
        last_date = (rel.get("last_active_date") or "")[:10]
        if last_date != today:
            rel["total_days_active"] = int(rel.get("total_days_active", 0)) + 1

            # Streak calculation
            if last_date:
                try:
                    last_dt = datetime.fromisoformat(last_date)
                    today_dt = datetime.fromisoformat(today)
                    diff_days = (today_dt - last_dt).days
                    if diff_days == 1:
                        # Consecutive day
                        rel["current_streak_days"] = int(rel.get("current_streak_days", 0)) + 1
                    elif diff_days > 1:
                        # Streak broken
                        rel["current_streak_days"] = 1
                except Exception:
                    rel["current_streak_days"] = 1
            else:
                rel["current_streak_days"] = 1

            # Update longest streak
            current = int(rel.get("current_streak_days", 0))
            longest = int(rel.get("longest_streak_days", 0))
            if current > longest:
                rel["longest_streak_days"] = current

            rel["last_active_date"] = today

            # Award daily streak XP (first activity of each new day)
            try:
                streak = int(rel.get("current_streak_days", 1))
                # Base +5 XP for daily activity, +bonus for streaks
                streak_bonus = min(streak, 10) * 2  # cap bonus at 20
                award_xp(5 + streak_bonus, reason=f"daily_activity:streak_{streak}")
            except Exception:
                pass

        _save_relationship(rel)
    except Exception as e:
        logger.debug("record_relationship_event failed: %s", e)


# ---------------------------------------------------------------------------
# Growth narrative generation
# ---------------------------------------------------------------------------

def get_growth_narrative(state: dict | None = None) -> str:
    """Generate a natural language summary of Layla's growth journey.

    Returns a human-readable paragraph describing the relationship history,
    maturity progress, and unlocked capabilities.
    """
    try:
        ms = get_state()
        rel = get_relationship_state()
        metrics = get_progress_metrics()
        # Spoken aloud ("I recently unlocked X"), so it obeys the same rule as the prompt
        # string: never announce a capability the operator has switched off.
        unlocks = [u for u in check_unlocks({"rank": ms.rank}) if u.get("enabled")]

        parts: list[str] = []

        # Duration
        days_active = int(rel.get("total_days_active", 0))
        if days_active > 0:
            parts.append(f"I've been active with you for {days_active} day{'s' if days_active != 1 else ''}.")

        # Conversations and learnings
        convos = metrics.get("conversations", 0)
        learnings = metrics.get("learnings", 0)
        aspects_used = metrics.get("distinct_aspects_used", 0)
        if convos > 0:
            msg = f"We've had {convos} conversation{'s' if convos != 1 else ''}"
            if aspects_used > 1:
                msg += f" across {aspects_used} aspects"
            msg += "."
            parts.append(msg)
        if learnings > 0:
            parts.append(f"I've learned {learnings} verified fact{'s' if learnings != 1 else ''} about your work.")

        # Strongest area (based on interaction history from personality evolution)
        try:
            from services.personality.evolution import get_personality_evolution
            evo = get_personality_evolution()
            # Check each aspect for interaction count to find strongest
            from services.personality.character_creator import ALL_ASPECTS, ASPECT_DEFAULTS
            best_aspect = ""
            best_count = 0
            for aid in ALL_ASPECTS:
                stats = evo.get_interaction_stats(aid)
                total = int(stats.get("total_interactions", 0))
                if total > best_count:
                    best_count = total
                    best_aspect = aid
            if best_aspect and best_count > 5:
                name = ASPECT_DEFAULTS.get(best_aspect, {}).get("name", best_aspect)
                parts.append(f"My strongest area is {name}.")
        except Exception:
            pass

        # Rank and phase
        parts.append(
            f"I'm at Rank {ms.rank} ({ms.phase} phase)."
        )

        # Streaks
        streak = int(rel.get("current_streak_days", 0))
        longest = int(rel.get("longest_streak_days", 0))
        if streak > 1:
            parts.append(f"Current streak: {streak} days.")
        if longest > streak and longest > 1:
            parts.append(f"Longest streak: {longest} days.")

        # Recent unlocks
        if unlocks:
            latest = unlocks[-1]
            parts.append(
                f"I recently unlocked {latest['name']} at Rank {latest['rank_required']}."
            )

        # Trust
        trust = int(rel.get("trust_events", 0))
        if trust > 0:
            parts.append(f"You've trusted me with {trust} risky action{'s' if trust != 1 else ''}.")

        return " ".join(parts) if parts else "Our journey is just beginning."
    except Exception as e:
        logger.debug("get_growth_narrative failed: %s", e)
        return "Our journey is just beginning."

