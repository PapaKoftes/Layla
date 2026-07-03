"""
self_consistency.py — majority vote over N sampled agent decisions.

Small models are noisy: the same prompt can yield different tool choices run to run.
Self-consistency samples the decision K times (temperature > 0) and keeps the modal
(action, tool) — a cheap accuracy lever for high-stakes turns where correctness beats
latency. Off by default (K=1) since it multiplies inference cost; opt in via
`self_consistency_samples`.

The vote itself is pure (no model) so it unit-tests without the inference engine:
callers sample the decisions, this picks the winner.
"""
from __future__ import annotations

from collections import Counter


def _decision_key(d: dict) -> tuple[str, str]:
    """Vote identity: the action, plus the tool name for tool actions."""
    action = (d.get("action") or "reason").strip().lower()
    tool = (str(d.get("tool") or "").strip()) if action == "tool" else ""
    return (action, tool)


def majority_decision(decisions: list[dict]) -> dict | None:
    """
    Return the decision whose (action, tool) is most common across ``decisions``.

    Ties break toward the earliest-sampled key (stable — Counter preserves insertion
    order). The returned dict is a copy of the first sample matching the winning key
    (so it keeps that sample's args/thought), annotated with ``_self_consistency``:
    {samples, agreement}. Returns None if there are no valid decisions.
    """
    valid = [d for d in decisions if isinstance(d, dict) and d.get("action")]
    if not valid:
        return None
    counts = Counter(_decision_key(d) for d in valid)
    top_key, top_n = counts.most_common(1)[0]
    for d in valid:
        if _decision_key(d) == top_key:
            winner = dict(d)
            winner["_self_consistency"] = {
                "samples": len(valid),
                "agreement": round(top_n / len(valid), 3),
            }
            return winner
    return dict(valid[0])


def self_consistency_samples(cfg: dict) -> int:
    """Resolve the configured sample count (clamped to a sane 1..7); 1 = disabled."""
    try:
        k = int(cfg.get("self_consistency_samples", 1) or 1)
    except (TypeError, ValueError):
        k = 1
    return max(1, min(7, k))
