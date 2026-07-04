"""Combined post-answer quality assessment (BL-100 grounding + BL-102 escalation) in one call.

This is the single hook the answer path invokes after producing a candidate answer. It runs RAG
grounding (cite-or-abstain) and the hybrid-escalation decision (re-ask a bigger model on low
confidence), returning one quality block:

    {grounding, confidence, escalate, escalation_model, abstain}

Fully gated: when neither grounding nor escalation is enabled it does no retrieval and no work
(a cheap no-op), so it is safe to call unconditionally. The caller decides what to do with the
block — attach it as response metadata, hedge when `abstain`, or re-ask `escalation_model` when
`escalate`. Keeping the policy in the caller (not here) means this stays pure + unit-testable.
"""
from __future__ import annotations


def assess_answer(answer: str, query: str, cfg: dict | None, *, current_model: str = "") -> dict:
    """Assess a candidate answer's groundedness + confidence. Pure; no side effects."""
    cfg = cfg or {}
    grounding_on = bool(cfg.get("grounding_enabled")) and str(cfg.get("grounding_mode", "flag")).lower() != "off"
    escalation_on = bool(cfg.get("hybrid_escalation_enabled"))
    if not grounding_on and not escalation_on:
        return {"grounding": {"enabled": False}, "confidence": 1.0, "escalate": False, "escalation_model": None, "abstain": False}

    grounding = {"enabled": False}
    if grounding_on:
        try:
            from services.retrieval.grounding import ground_answer
            grounding = ground_answer(answer, query, cfg)
        except Exception:
            grounding = {"enabled": False}

    confidence, escalate, target = 1.0, False, None
    try:
        from services.llm.hybrid_escalation import escalation_decision
        d = escalation_decision(answer, cfg, grounding=grounding, current_model=current_model)
        confidence, escalate, target = d["confidence"], d["escalate"], d["escalation_model"]
    except Exception:
        pass

    abstain = bool(grounding.get("enabled") and grounding.get("abstain"))
    return {
        "grounding": grounding,
        "confidence": confidence,
        "escalate": escalate,
        "escalation_model": target,
        "abstain": abstain,
    }
