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

PhaseId = Literal["nascent", "apprentice", "adept", "veteran", "transcendent"]


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
        return "nascent"
    if r <= 5:
        return "apprentice"
    if r <= 8:
        return "adept"
    if r <= 12:
        return "veteran"
    return "transcendent"


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
    if phase_raw in ("nascent", "apprentice", "adept", "veteran", "transcendent"):
        phase = phase_raw  # type: ignore[assignment]
    return MaturityState(xp=xp, rank=rank, phase=phase)


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
    _persist_state(MaturityState(xp=0, rank=0, phase="nascent"), last_event="seed")

