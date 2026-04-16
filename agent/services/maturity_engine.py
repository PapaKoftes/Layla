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

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

PhaseId = Literal["awakening", "attunement", "resonance", "sovereignty", "transcendence"]


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

