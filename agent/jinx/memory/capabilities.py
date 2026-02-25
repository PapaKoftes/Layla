"""
Evolution layer: capability growth model, scoring, scheduler selection.

- Decay risk from last_practiced_at
- Trend from recent capability_events
- Reinforcement priority for scheduler
- record_practice() updates capability + events; optional cross-domain propagation
- get_next_plan_for_study() returns plan by urgency + diversification (when enabled)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import db as _db

logger = logging.getLogger("layla")

DECAY_THRESHOLD_DAYS = 7
DECAY_FULL_DAYS = 30
DEFAULT_DELTA_LEVEL_PRACTICE = 0.02
DEFAULT_DELTA_CONFIDENCE_PRACTICE = 0.01
RECENT_EVENTS_FOR_TREND = 3
SCHEDULER_WINDOW_RUNS = 5
SCHEDULER_MAX_SAME_DOMAIN_IN_WINDOW = 2
USEFULNESS_THRESHOLD_LOW = 0.3  # Below this: minimal reinforce, no cross-domain


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago(iso_ts: str | None) -> float:
    if not iso_ts:
        return 999.0
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0.0, delta.total_seconds() / 86400.0)
    except Exception:
        return 999.0


def compute_decay_risk(last_practiced_at: str | None) -> float:
    """0.0 at 0 days, 1.0 at DECAY_FULL_DAYS. Linear in between."""
    days = _days_ago(last_practiced_at)
    if days <= 0:
        return 0.0
    return min(1.0, days / DECAY_FULL_DAYS)


def compute_trend(domain_id: str) -> str:
    """improving | stable | weakening | stagnant from last RECENT_EVENTS_FOR_TREND events."""
    events = _db.get_recent_capability_events(domain_id, n=RECENT_EVENTS_FOR_TREND)
    if not events:
        return "stable"
    net = sum(e.get("delta_level") or 0 for e in events)
    cap = _db.get_capability(domain_id)
    last = (cap or {}).get("last_practiced_at")
    days = _days_ago(last)
    if days > 14 and (cap or {}).get("practice_count", 0) > 0:
        return "stagnant"
    if net > 0.01:
        return "improving"
    if net < -0.01:
        return "weakening"
    return "stable"


def compute_reinforcement_priority(level: float, decay_risk: float, trend: str) -> float:
    """Higher = more urgent to reinforce. 0-1."""
    low_level = 0.4 * (1.0 - level)
    decay = 0.3 * decay_risk
    bad_trend = 0.2 if trend in ("weakening", "stagnant") else 0.0
    improving_bonus = 0.0 if trend == "improving" else 0.1
    raw = low_level + decay + bad_trend + improving_bonus
    return min(1.0, max(0.0, raw))


def run_learning_validation(outcome_summary: str | None) -> float:
    """
    Learning validation pass: did this improve practical ability?
    Returns usefulness_score 0-1 based on actionability, transferability, real-world relevance.
    Low score -> weak reinforcement, no cross-domain (memory hygiene).
    """
    if not outcome_summary or not isinstance(outcome_summary, str):
        return 0.2
    s = outcome_summary.strip()
    if len(s) < 50:
        return 0.2
    if len(s) < 150:
        return 0.4
    # Substantial outcome: check for structure (bullets, numbers, key terms)
    lower = s.lower()
    has_structure = any(x in lower for x in ("1.", "2.", "- ", "* ", "key", "step", "first", "then"))
    return 0.7 if has_structure else 0.5


def record_practice(
    domain_id: str,
    mission_id: str | None = None,
    delta_level: float = DEFAULT_DELTA_LEVEL_PRACTICE,
    delta_confidence: float = DEFAULT_DELTA_CONFIDENCE_PRACTICE,
    notes: str | None = None,
    propagate_cross_domain: bool = True,
    usefulness_score: float = 0.5,
    learning_quality_score: float | None = None,
) -> int:
    """
    Record a practice event, update capability row, optionally propagate to dependent domains.
    When usefulness_score < USEFULNESS_THRESHOLD_LOW: minimal reinforcement, no cross-domain (memory hygiene).
    Propagation uses usefulness-weighted deltas so low-value learning does not spread.
    Returns capability_events.id.
    """
    usefulness_score = max(0.0, min(1.0, usefulness_score))
    # Low usefulness: do NOT strongly reinforce; minimal delta only
    if usefulness_score < USEFULNESS_THRESHOLD_LOW:
        effective_delta_level = 0.005
        effective_delta_confidence = 0.0
        propagate_cross_domain = False
    else:
        effective_delta_level = delta_level * usefulness_score
        effective_delta_confidence = delta_confidence * usefulness_score

    if learning_quality_score is None:
        learning_quality_score = usefulness_score
    learning_quality_score = max(0.0, min(1.0, learning_quality_score))
    _db.migrate()
    event_id = _db.insert_capability_event(
        domain_id=domain_id,
        event_type="practice",
        mission_id=mission_id,
        delta_level=effective_delta_level,
        delta_confidence=effective_delta_confidence,
        notes=notes,
        usefulness_score=usefulness_score,
        learning_quality_score=learning_quality_score,
    )
    cap = _db.get_capability(domain_id)
    if not cap:
        return event_id
    level = min(1.0, max(0.0, (cap.get("level") or 0.5) + effective_delta_level))
    confidence = min(1.0, max(0.0, (cap.get("confidence") or 0.5) + effective_delta_confidence))
    practice_count = (cap.get("practice_count") or 0) + 1
    now = _now_iso()
    decay_risk = compute_decay_risk(now)
    events = _db.get_recent_capability_events(domain_id, n=RECENT_EVENTS_FOR_TREND)
    net = sum(e.get("delta_level") or 0 for e in events)
    if net > 0.01:
        trend = "improving"
    elif net < -0.01:
        trend = "weakening"
    else:
        trend = "stable"
    reinforcement_priority = compute_reinforcement_priority(level, decay_risk, trend)
    _db.update_capability(
        domain_id=domain_id,
        level=level,
        confidence=confidence,
        trend=trend,
        last_practiced_at=now,
        decay_risk=decay_risk,
        reinforcement_priority=reinforcement_priority,
        practice_count=practice_count,
    )
    # Cross-domain: only when usefulness is above threshold; deltas weighted by usefulness
    if propagate_cross_domain and usefulness_score >= USEFULNESS_THRESHOLD_LOW:
        for dep in _db.get_capability_dependencies():
            if dep.get("source_domain_id") != domain_id:
                continue
            tgt = dep.get("target_domain_id")
            w = dep.get("weight") or 0.2
            if tgt:
                cross_delta = min(0.01, w * effective_delta_level * usefulness_score)
                _db.insert_capability_event(
                    domain_id=tgt,
                    event_type="cross_signal",
                    mission_id=mission_id,
                    delta_level=cross_delta,
                    delta_confidence=0,
                    notes=f"from {domain_id}",
                    usefulness_score=usefulness_score,
                    learning_quality_score=learning_quality_score,
                )
                tgt_cap = _db.get_capability(tgt)
                if tgt_cap:
                    tgt_level = min(1.0, max(0.0, (tgt_cap.get("level") or 0.5) + cross_delta))
                    tgt_decay = compute_decay_risk(tgt_cap.get("last_practiced_at"))
                    tgt_trend = compute_trend(tgt)
                    tgt_rp = compute_reinforcement_priority(tgt_level, tgt_decay, tgt_trend)
                    _db.update_capability(
                        domain_id=tgt,
                        level=tgt_level,
                        confidence=tgt_cap.get("confidence") or 0.5,
                        trend=tgt_trend,
                        last_practiced_at=tgt_cap.get("last_practiced_at"),
                        decay_risk=tgt_decay,
                        reinforcement_priority=tgt_rp,
                        practice_count=tgt_cap.get("practice_count") or 0,
                    )
    return event_id


def get_urgency_scores(domain_ids: list[str] | None = None) -> list[tuple[str, float]]:
    """
    Returns list of (domain_id, urgency) sorted by urgency descending.
    If domain_ids is None, use all capabilities.
    """
    caps = _db.get_capabilities()
    if domain_ids is not None:
        domain_set = set(domain_ids)
        caps = [c for c in caps if c.get("domain_id") in domain_set]
    out = []
    for c in caps:
        did = c.get("domain_id")
        if not did:
            continue
        rp = c.get("reinforcement_priority") or 0.5
        decay = c.get("decay_risk") or 0.5
        last = c.get("last_practiced_at")
        days = _days_ago(last)
        time_factor = min(1.0, days / 14.0)
        urgency = 0.5 * rp + 0.3 * decay + 0.2 * time_factor
        out.append((did, urgency))
    out.sort(key=lambda x: -x[1])
    return out


def get_next_plan_for_study(
    active_plans: list[dict],
    use_capabilities: bool = True,
    diversification_window: int = SCHEDULER_WINDOW_RUNS,
    max_same_domain: int = SCHEDULER_MAX_SAME_DOMAIN_IN_WINDOW,
) -> tuple[dict | None, str | None]:
    """
    Pick the best plan for the next study run.
    Returns (plan, domain_id). domain_id is None for legacy topic-only selection.
    When use_capabilities is True and plans have domain_id (or we map topic->domain),
    uses urgency + diversification. Otherwise falls back to min(last_studied).
    """
    if not active_plans:
        return None, None
    history = _db.get_scheduler_history(n=diversification_window) if use_capabilities else []
    domain_counts = {}
    for h in history:
        d = h.get("domain_id") or ""
        if d:
            domain_counts[d] = domain_counts.get(d, 0) + 1

    if not use_capabilities:
        plan = min(active_plans, key=lambda p: (p.get("last_studied") or "") or "0000")
        return plan, plan.get("domain_id")

    # Build (plan, domain_id, urgency) for plans that have or can get a domain_id
    plan_domain_urgency: list[tuple[dict, str, float]] = []
    topic_to_domain = _topic_to_domain_map()
    for plan in active_plans:
        domain_id = plan.get("domain_id") or topic_to_domain.get((plan.get("topic") or "").strip().lower())
        if not domain_id:
            continue
        cap = _db.get_capability(domain_id)
        if not cap:
            continue
        rp = cap.get("reinforcement_priority") or 0.5
        decay = cap.get("decay_risk") or 0.5
        last = cap.get("last_practiced_at")
        days = _days_ago(last)
        time_factor = min(1.0, days / 14.0)
        urgency = 0.5 * rp + 0.3 * decay + 0.2 * time_factor
        plan_domain_urgency.append((plan, domain_id, urgency))

    if not plan_domain_urgency:
        plan = min(active_plans, key=lambda p: (p.get("last_studied") or "") or "0000")
        return plan, plan.get("domain_id")

    # Balance: down-rank domains that are far above median level (prevent over-specialization)
    levels = [(_db.get_capability(did) or {}).get("level") or 0.5 for _, did, _ in plan_domain_urgency]
    median_level = sorted(levels)[len(levels) // 2] if levels else 0.5
    balance_threshold = 0.3
    adjusted = []
    for plan, domain_id, urgency in plan_domain_urgency:
        cap = _db.get_capability(domain_id) or {}
        level = cap.get("level") or 0.5
        if level > median_level + balance_threshold:
            urgency = urgency * 0.7
        adjusted.append((plan, domain_id, urgency))
    plan_domain_urgency = adjusted

    plan_domain_urgency.sort(key=lambda x: -x[2])
    for plan, domain_id, _ in plan_domain_urgency:
        if domain_counts.get(domain_id, 0) >= max_same_domain:
            continue
        return plan, domain_id
    return plan_domain_urgency[0][0], plan_domain_urgency[0][1]


def _topic_to_domain_map() -> dict[str, str]:
    """Heuristic: topic substring -> domain_id. Extend as needed."""
    m = {}
    for d in _db.get_capability_domains():
        did = d.get("id", "")
        name = (d.get("name") or "").lower()
        if did and name:
            m[name] = did
        if did == "coding":
            for k in ("code", "python", "refactor", "implement"):
                m[k] = did
        if did == "research":
            for k in ("research", "synthesis", "deep dive"):
                m[k] = did
        if did == "writing":
            for k in ("write", "documentation", "doc"):
                m[k] = did
        if did == "planning":
            for k in ("plan", "roadmap", "task"):
                m[k] = did
    return m


def apply_decay_if_needed(decay_threshold_days: float = DECAY_THRESHOLD_DAYS) -> None:
    """For capabilities not practiced in decay_threshold_days, add decay_risk bump and optional decay_tick event."""
    now = _now_iso()
    for cap in _db.get_capabilities():
        domain_id = cap.get("domain_id")
        last = cap.get("last_practiced_at")
        if _days_ago(last) < decay_threshold_days:
            continue
        decay_risk = compute_decay_risk(last)
        trend = compute_trend(domain_id)
        if trend == "stagnant":
            pass
        elif trend == "stable":
            trend = "weakening"
        rp = compute_reinforcement_priority(
            cap.get("level") or 0.5,
            decay_risk,
            trend,
        )
        _db.insert_capability_event(
            domain_id=domain_id,
            event_type="decay_tick",
            delta_level=-0.01,
            delta_confidence=0,
            notes="decay",
        )
        level = max(0.0, (cap.get("level") or 0.5) - 0.01)
        _db.update_capability(
            domain_id=domain_id,
            level=level,
            confidence=cap.get("confidence") or 0.5,
            trend=trend,
            last_practiced_at=last,
            decay_risk=decay_risk,
            reinforcement_priority=rp,
            practice_count=cap.get("practice_count") or 0,
        )
    return None
