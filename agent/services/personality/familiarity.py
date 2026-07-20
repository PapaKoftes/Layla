"""Familiarity — an auditable measure of how much Layla actually knows about the operator.

WHY THIS EXISTS, AND WHY IT IS NOT MATURITY XP
----------------------------------------------
The rank/XP badge was described as "a visual indicator of how much she's learned about you".
It is not, and never was. `maturity_engine.award_xp` is called from 14 sites and every one of
them counts an ACTION, not a piece of knowledge:

    conversation_turn 3 · tool_success 5 · file_stored 5 · daily_activity 5-25 · file_ingested 8
    learning_saved 10 · fact_verified 12 · approval_executed 15 · plan_executed 20 (x3 sites)
    study_session 20 · capability_practice 30 · research_mission 50

Rank is just that total crossing fixed thresholds (`_XP_TO_NEXT`). It is an activity odometer.
Relabelling it "how well she knows you" would replace one false claim with another, so this
module computes a separate indicator from stores that genuinely are about the operator, and
publishes the source of every number so the operator can check it.

WHAT IS DELIBERATELY EXCLUDED, AND WHY
-------------------------------------
* `learnings` — NOT about the operator. On a real 28-row DB the contents are generic world and
  docstring text re-ingested from Layla's own replies ("Paris serves as the political ... center
  of France", "n (int): The number to check for primality"). Counting those as "facts she knows
  about you" is exactly the lie this module exists to avoid. The growth panel already reports
  them separately, under "Knowledge".
* `entities` — same problem: extraction noise ("key concepts", "the world", "research what").
* `conversation_messages` — a volume count, not knowledge. It appears only as context, never in
  the fraction.

THE CONTRACT
------------
`known` / `total` is a fraction over a FIXED roster of specific things she can know, each of
which is returned with its actual stored value. Nothing unbounded is folded into the
percentage — counts that have no denominator are returned as `context` rows instead, so the
headline number can always be recomputed by hand from the list underneath it.

Best-effort throughout: never raises.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("layla.familiarity")

# ── The roster: specific things she can know about the operator ──────────────
# Each entry is a user_identity key written by onboarding (services/user/onboarding_interview.py)
# or by the operator quiz (services/personality/operator_quiz.py). A key is "known" when it holds
# a non-empty value. Adding a row here widens the denominator, so only add keys that are really
# about the operator and that some code path really writes.
PROFILE_ROSTER: tuple[tuple[str, str], ...] = (
    ("name", "Your name"),
    ("goals_summary", "What you're working toward"),
    ("work_domains", "Your work domains"),
    ("communication_style", "How you like to be spoken to"),
    ("formality_level", "Formality"),
    ("humour_preference", "Humour"),
    ("assistant_style", "Assistant style"),
    ("preferred_response_length", "Answer length"),
    ("proactivity_level", "How proactive to be"),
    ("collaboration_mode", "How you like to work together"),
    ("learning_mode", "How you like to learn things"),
    ("debug_style", "How you debug"),
    ("indent_style", "Indentation"),
    ("risk_tolerance", "Risk tolerance"),
    ("risk_execution", "How you ship risky changes"),
    ("status_update_style", "How you want status reports"),
    ("watch_folders", "Folders you asked her to watch"),
)

# The six operator stats (stat_technical, stat_creative, ...). Absent keys read as the neutral
# default 5 elsewhere, so presence — not value — is what counts as "known".
TRAIT_LABELS: dict[str, str] = {
    "technical": "Technical",
    "creative": "Creative",
    "analytical": "Analytical",
    "social": "Social",
    "patience": "Patience",
    "ambition": "Ambition",
}

_BASIS_PROFILE = "user_identity — written by the onboarding interview and the operator quiz"
_BASIS_TRAITS = "user_identity stat_* — set by the quiz, or by `layla stat <name> <1-10>`"


def _identity() -> dict[str, str]:
    try:
        from layla.memory.db import get_all_user_identity

        return get_all_user_identity() or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("familiarity identity load failed: %s", e)
        return {}


def _roster(uid: dict[str, str]) -> list[dict[str, Any]]:
    """The roster with each row's actual stored value. Pure — one identity dict in, rows out."""
    rows: list[dict[str, Any]] = []
    for key, label in PROFILE_ROSTER:
        val = str(uid.get(key) or "").strip()
        rows.append({"key": key, "label": label, "value": _short(val), "known": bool(val), "group": "profile"})
    for stat, label in TRAIT_LABELS.items():
        raw = str(uid.get(f"stat_{stat}") or "").strip()
        rows.append(
            {"key": f"stat_{stat}", "label": label + " (1-10)", "value": raw, "known": bool(raw), "group": "traits"}
        )
    return rows


def _short(value: str, limit: int = 60) -> str:
    v = " ".join(str(value or "").split())
    return v if len(v) <= limit else v[: limit - 1] + "…"


def _interaction_context(uid: dict[str, str]) -> dict[str, Any]:
    """Exchanges per aspect, from the interaction_history_<aspect> blobs evolution.py writes."""
    total = 0
    aspects = 0
    for key, raw in uid.items():
        if not key.startswith("interaction_history_"):
            continue
        try:
            blob = json.loads(raw or "{}")
        except Exception:
            continue
        n = int(blob.get("total_interactions") or 0)
        if n > 0:
            total += n
            aspects += 1
    return {"exchanges": total, "aspects": aspects}


def _relationship_context(uid: dict[str, str]) -> dict[str, Any]:
    try:
        rel = json.loads(uid.get("maturity_relationship") or "{}")
    except Exception:
        rel = {}
    return {
        "days_active": int(rel.get("total_days_active") or 0),
        "since": str(rel.get("first_interaction") or "")[:10],
        "longest_streak": int(rel.get("longest_streak_days") or 0),
    }


def _drifted_aspects(uid: dict[str, str]) -> int:
    """Aspects whose tone has actually moved toward this operator (evolution.py writes these)."""
    n = 0
    for key, raw in uid.items():
        if not key.startswith("personality_drift_"):
            continue
        try:
            blob = json.loads(raw or "{}")
        except Exception:
            continue
        if any(abs(float(v or 0)) > 0.0 for v in blob.values()):
            n += 1
    return n


def _manual_notes() -> int:
    try:
        from services.personality.operating_manual import list_notes

        return len(list_notes() or [])
    except Exception as e:  # noqa: BLE001
        logger.debug("familiarity manual notes failed: %s", e)
        return 0


def _practised_domains() -> tuple[int, int]:
    """(practised, total) capability domains. Practised means practice_count > 0 — a domain that
    has only ever decayed has not been practised, and must not be counted as one that has."""
    try:
        from layla.memory.capabilities_db import get_capabilities

        caps = get_capabilities() or []
        return sum(1 for c in caps if int(c.get("practice_count") or 0) > 0), len(caps)
    except Exception as e:  # noqa: BLE001
        logger.debug("familiarity capabilities failed: %s", e)
        return 0, 0


def get_familiarity() -> dict[str, Any]:
    """How much she knows about the operator, as a checkable fraction plus context counts."""
    try:
        uid = _identity()

        answers = _roster(uid)
        known = sum(1 for a in answers if a["known"])
        total = len(answers)
        pct = int(round(100.0 * known / total)) if total else 0

        inter = _interaction_context(uid)
        rel = _relationship_context(uid)
        drifted = _drifted_aspects(uid)
        notes = _manual_notes()
        practised, domains_total = _practised_domains()

        context: list[dict[str, Any]] = [
            {
                "id": "exchanges",
                "label": "Exchanges with you",
                "value": (
                    f"{inter['exchanges']} across {inter['aspects']} aspect"
                    f"{'' if inter['aspects'] == 1 else 's'}"
                    if inter["exchanges"]
                    else "none yet"
                ),
                "basis": "user_identity interaction_history_<aspect> — counted per aspect by personality evolution",
            },
            {
                "id": "days",
                "label": "Days you've been active",
                "value": (
                    f"{rel['days_active']}"
                    + (f" since {rel['since']}" if rel["since"] else "")
                    + (f" · longest streak {rel['longest_streak']}" if rel["longest_streak"] else "")
                    if rel["days_active"]
                    else "none yet"
                ),
                "basis": "user_identity.maturity_relationship — one day counted per calendar day with activity",
            },
            {
                "id": "voice",
                "label": "Aspects whose tone has adapted to you",
                "value": str(drifted),
                "basis": "user_identity personality_drift_<aspect> — nonzero drift on any axis",
            },
            {
                "id": "manual",
                "label": "Standing instructions you've given her",
                "value": str(notes),
                # NOT "added from Library → Operating manual": routers/operating_manual.py exists but
                # nothing in ui/ calls it, so naming a screen would be a false pointer — the same class
                # of claim this whole change is removing. Name the interface that is actually there.
                "basis": "operating_manual.db manual_note — added via POST /manual/notes (no UI yet)",
            },
            {
                "id": "domains",
                "label": "Skill domains practised with you",
                "value": f"{practised} of {domains_total}" if domains_total else "no domains tracked",
                "basis": "capabilities.practice_count — a domain only counts once a real turn practised it",
            },
        ]

        return {
            "ok": True,
            "known": known,
            "total": total,
            "pct": pct,
            "answers": answers,
            "context": context,
            "basis": (
                f"{known} of {total} specific things about you are on file. "
                "Every row below is a stored value you can check — nothing is inferred or weighted. "
                "The counts underneath are shown separately because they have no maximum, "
                "so they are not part of the fraction."
            ),
            "sources": {"profile": _BASIS_PROFILE, "traits": _BASIS_TRAITS},
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("get_familiarity failed: %s", e)
        # Same key shape as the success path — a consumer that indexes `sources` should not get a
        # KeyError on the one path where something already went wrong.
        return {
            "ok": False, "known": 0, "total": 0, "pct": 0,
            "answers": [], "context": [], "basis": "", "sources": {},
        }


def knows_operator() -> bool:
    """True once the operator has actually told her something about themselves.

    THE HONEST TRIGGER FOR EARLY-PHASE RESTRAINT. `llm_decision`'s observation mode used to ask
    `is_early_phase(maturity.phase)`, and phase is `phase_for_rank(rank)` — an activity odometer.
    That made caution wear off by grinding XP rather than by getting to know the operator, and it
    is the same substitution `familiarity_line` already made for the rank<1 directive in
    system_head_builder. "Should I hold back?" is a question about knowledge, so read knowledge.

    False when nothing is on file, which is the conservative direction: an empty profile keeps
    the restraint on. Any failure also reads False for the same reason.
    """
    try:
        rows = _roster(_identity())
        return any(r["known"] for r in rows)
    except Exception as e:  # noqa: BLE001
        logger.debug("knows_operator failed: %s", e)
        return False


def familiarity_line() -> str:
    """One true sentence about familiarity, for the system prompt. Exactly one DB read.

    This replaces BOTH of the rank-derived strings that used to reach the model:

      * `maturity_engine.get_unlocks_text()` — "Your current capabilities: A, B, C", a second
        capability source competing with .identity/capabilities.md. This line names no
        capability at all, so it cannot contradict the manifest.
      * the rank<1 "early growth phase" directive in system_head_builder — a restraint keyed on
        rank. Rank was standing in for "she doesn't know this person yet", which is now measured
        directly instead of guessed from an activity counter.

    Deliberately does NOT call get_familiarity(): that also queries capabilities and opens
    operating_manual.db, and this runs on every turn.
    """
    try:
        uid = _identity()
        rows = _roster(uid)
        total = len(rows)
        if not total:
            return ""
        known = sum(1 for r in rows if r["known"])
        if known <= 0:
            return (
                "You do not know this operator's preferences yet. Ask rather than assume, and do not "
                "proactively suggest topics or actions they have not raised."
            )
        return (
            f"You have {known} of {total} of this operator's stated preferences on file "
            "(name, working style, tolerances). That is how well you know them, not what you can do."
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("familiarity_line failed: %s", e)
        return ""
