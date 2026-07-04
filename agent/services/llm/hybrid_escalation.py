"""Hybrid escalation — re-ask a bigger model when the small model's answer looks low-confidence
(BL-102 / UPG-01).

The DECISION is heuristic + deterministic (unit-testable without a model); the actual re-run is
performed by the caller with the configured `escalation_model`. Confidence signals are cheap and
model-free:

  • hedging / uncertainty phrases ("I'm not sure", "I think", "possibly", "hard to say")
  • explicit abstain / "I don't know" / can't-answer
  • a low RAG grounding score (from BL-100 `check_grounding`), when provided
  • degenerate answers (empty / a bare fragment for a non-trivial question)

Escalation only fires when it's enabled AND a distinct bigger model is configured AND the
confidence is below the threshold — so on a single-model box it's always a no-op.
"""
from __future__ import annotations

import re

# Mild hedging cues — each chips a little off confidence (whole-phrase, case-insensitive).
_HEDGES = (
    "i think ", "i believe ", "i guess", "possibly", "perhaps", "maybe", "it might be",
    "it may be", "hard to say", "difficult to say", "unclear", "as far as i know",
    "correct me if", "off the top of my head", "if i recall",
)
# Strong uncertainty — a soft abstain; caps confidence low on its own.
_SOFT_ABSTAINS = (
    "i'm not sure", "i am not sure", "not entirely sure", "not certain", "i'm not certain",
    "i could be wrong", "can't be sure", "cannot be sure",
)
# Explicit "can't answer" — the strongest low-confidence signal.
_ABSTAINS = (
    "i don't know", "i do not know", "i cannot answer", "i can't answer", "no idea",
    "i don't have enough", "insufficient information", "i'm unable to", "cannot determine",
)


def answer_confidence(answer: str, *, grounding: dict | None = None) -> float:
    """Estimate answer confidence in [0, 1] from cheap heuristics (+ optional grounding)."""
    if answer is None:
        return 0.0
    text = answer.strip()
    low = text.lower()
    if not text:
        return 0.0

    conf = 1.0
    # Explicit abstain dominates; a soft abstain ("not sure") caps confidence low too.
    if any(a in low for a in _ABSTAINS):
        conf = min(conf, 0.15)
    if any(s in low for s in _SOFT_ABSTAINS):
        conf = min(conf, 0.4)
    # Each distinct mild hedge chips away (capped so a naturally cautious tone isn't over-penalized).
    hedge_hits = sum(1 for h in _HEDGES if h in low)
    conf -= min(0.5, 0.15 * hedge_hits)
    # A bare fragment as a whole answer is usually low-confidence.
    if len(re.findall(r"\w+", text)) < 4:
        conf -= 0.3
    # RAG grounding (BL-100): unsupported claims strongly lower confidence.
    if isinstance(grounding, dict) and grounding.get("enabled"):
        overall = float(grounding.get("overall", 1.0))
        if grounding.get("unsupported"):
            conf = min(conf, 0.2 + 0.6 * overall)  # e.g. overall 0 → 0.2, overall 0.5 → 0.5
    return max(0.0, min(1.0, conf))


def escalation_model(cfg: dict | None) -> str | None:
    """The configured bigger model to escalate to (or None if unset)."""
    cfg = cfg or {}
    m = str(cfg.get("escalation_model") or "").strip()
    return m or None


def should_escalate(answer: str, cfg: dict | None, *, grounding: dict | None = None, current_model: str = "") -> bool:
    """True if the caller should re-ask `escalation_model`. Requires: feature enabled, a distinct
    bigger model configured, and confidence below `escalation_confidence_threshold` (default 0.5)."""
    cfg = cfg or {}
    if not cfg.get("hybrid_escalation_enabled", False):
        return False
    big = escalation_model(cfg)
    if not big or big == (current_model or "").strip():
        return False  # nothing to escalate to (single-model box)
    threshold = float(cfg.get("escalation_confidence_threshold", 0.5))
    return answer_confidence(answer, grounding=grounding) < threshold


def escalation_decision(answer: str, cfg: dict | None, *, grounding: dict | None = None, current_model: str = "") -> dict:
    """Full decision record (handy for logging/telemetry): confidence, threshold, target, escalate."""
    cfg = cfg or {}
    conf = answer_confidence(answer, grounding=grounding)
    big = escalation_model(cfg)
    threshold = float(cfg.get("escalation_confidence_threshold", 0.5))
    escalate = should_escalate(answer, cfg, grounding=grounding, current_model=current_model)
    return {"confidence": round(conf, 3), "threshold": threshold, "escalation_model": big, "escalate": escalate}
