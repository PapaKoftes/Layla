"""
Post-run outcome evaluation (North Star execution loop: evaluate → improve).
Heuristic score + issues; feeds reflection_engine and optional planner hints.
"""
from __future__ import annotations

from typing import Any


def evaluate_outcome(state: dict[str, Any]) -> dict[str, Any]:
    """
    Returns {score: 0..1, issues: [str], success: bool, tool_ok: int, tool_fail: int}.
    Uses status, tool step results, last_verification, environment_aligned when present.
    """
    steps = state.get("steps") or []
    tool_steps = [s for s in steps if s.get("action") and s["action"] not in ("reason", "think", "client_abort")]
    ok_n = 0
    fail_n = 0
    issues: list[str] = []
    for s in tool_steps:
        r = s.get("result")
        if isinstance(r, dict):
            if r.get("ok", False):
                ok_n += 1
            else:
                fail_n += 1
                err = (r.get("error") or r.get("reason") or "failed")[:120]
                issues.append(f"{s.get('action')}: {err}")
        else:
            fail_n += 1
            issues.append(f"{s.get('action')}: non-dict result")

    status = str(state.get("status") or "")
    finished = status == "finished"
    score = 0.85 if finished else 0.35
    if fail_n:
        score *= max(0.15, 1.0 - 0.12 * fail_n)
    if not tool_steps and finished:
        score = min(score, 0.7)
        issues.append("no_tool_steps: reply-only finish")

    lv = state.get("last_verification")
    if isinstance(lv, dict):
        if lv.get("retry_suggested") and not lv.get("progress_made", True):
            score *= 0.85
            issues.append("verification: retry_suggested without progress")
    if state.get("environment_aligned") is False:
        score *= 0.8
        issues.append("environment_aligned_false")

    success = finished and fail_n == 0 and state.get("environment_aligned") is not False
    score = max(0.0, min(1.0, float(score)))
    return {
        "score": round(score, 3),
        "issues": issues[:12],
        "success": success,
        "tool_ok": ok_n,
        "tool_fail": fail_n,
        "status": status,
    }


def policy_caps_trace_from_evaluation(ev: dict) -> dict[str, object]:
    """Structured caps derived from a stored outcome (for planner / UI)."""
    from services.decision_policy import caps_from_outcome_evaluation

    return caps_from_outcome_evaluation(ev).to_trace_dict()


def api_confidence_heuristic(state: dict[str, Any]) -> dict[str, Any]:
    """
    Non-calibrated 0..1 score for API consumers. Do not treat as calibrated probability.
    Combines evaluate_outcome score with refusal / terminal status.
    """
    ev = evaluate_outcome(state)
    score = float(ev.get("score") or 0.5)
    if state.get("refused"):
        score *= 0.2
    st = str(state.get("status") or "")
    if st not in ("finished", "plan_completed"):
        score *= 0.75
    if st in ("timeout", "parse_failed", "system_busy"):
        score *= 0.5
    score = max(0.0, min(1.0, score))
    return {
        "value": round(score, 3),
        "calibrated": False,
        "basis": "outcome_evaluation_heuristic",
        "tool_fail": int(ev.get("tool_fail") or 0),
    }
