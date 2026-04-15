"""
Post-run outcome evaluation (North Star execution loop: evaluate → improve).
Heuristic score + issues; feeds reflection_engine and optional planner hints.
"""
from __future__ import annotations

from typing import Any


def evaluate_validation_matrix(state: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic multi-dimensional validation matrix.
    Each dimension returns 0..1 plus a short reason list.
    """
    steps = state.get("steps") or []
    tool_steps = [
        s for s in steps
        if isinstance(s, dict)
        and s.get("action")
        and s.get("action") not in ("reason", "think", "client_abort", "none", "pre_read_probe")
    ]

    ok_n = 0
    fail_n = 0
    det_fail_n = 0
    artifacts_ok = 0
    artifacts_total = 0
    reasons: dict[str, list[str]] = {k: [] for k in ("tool_accuracy", "completeness", "artifact_verification", "step_efficiency", "consistency")}

    written_paths: list[str] = []
    for s in tool_steps:
        action = str(s.get("action") or "")
        r = s.get("result")
        if isinstance(r, dict):
            if r.get("ok", False):
                ok_n += 1
            else:
                fail_n += 1
            dv = r.get("_deterministic_verify")
            if isinstance(dv, dict) and dv.get("ok") is False:
                det_fail_n += 1
                reasons["artifact_verification"].append(f"{action}:det_fail:{dv.get('reason')}")
            if action in ("write_file", "replace_in_file", "apply_patch", "write_files_batch"):
                artifacts_total += 1
                if r.get("ok"):
                    artifacts_ok += 1
                p = r.get("path")
                if isinstance(p, str) and p.strip():
                    written_paths.append(p.strip())
        else:
            fail_n += 1
            reasons["tool_accuracy"].append(f"{action}:non_dict_result")

    tool_total = max(0, ok_n + fail_n)
    tool_accuracy = (ok_n / tool_total) if tool_total else (1.0 if str(state.get("status") or "") == "finished" else 0.0)
    if tool_total and fail_n:
        reasons["tool_accuracy"].append(f"tool_fail:{fail_n}")

    status = str(state.get("status") or "")
    objective_complete = bool(state.get("objective_complete"))
    finished = status == "finished"
    completeness = 1.0 if (finished and objective_complete) else (0.5 if finished else 0.0)
    if not objective_complete:
        reasons["completeness"].append("objective_complete_false")
    if not finished:
        reasons["completeness"].append(f"status:{status or 'unknown'}")

    if artifacts_total:
        artifact_verification = artifacts_ok / max(1, artifacts_total)
        if artifacts_ok < artifacts_total:
            reasons["artifact_verification"].append(f"artifact_fail:{artifacts_total - artifacts_ok}")
    else:
        artifact_verification = 1.0

    # Efficiency: compare tool_calls to configured max_tool_calls (best-effort).
    max_tools = None
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        try:
            max_tools = int(cfg.get("max_tool_calls", 20) or 20)
        except (TypeError, ValueError):
            max_tools = 20
    except Exception:
        max_tools = 20
    tc = int(state.get("tool_calls") or tool_total or 0)
    if max_tools and max_tools > 0:
        ratio = tc / float(max_tools)
        step_efficiency = 1.0 if ratio <= 0.8 else max(0.0, 1.0 - (ratio - 0.8) * 2.5)
        if ratio > 0.8:
            reasons["step_efficiency"].append(f"tool_budget_high:{ratio:.2f}")
    else:
        step_efficiency = 0.5

    # Consistency: detect immediate rewrites to same path (rough heuristic).
    seen: set[str] = set()
    rewrites = 0
    for p in written_paths:
        if p in seen:
            rewrites += 1
        seen.add(p)
    consistency = 1.0 if rewrites == 0 else max(0.0, 1.0 - min(1.0, rewrites * 0.25))
    if rewrites:
        reasons["consistency"].append(f"multiple_writes_same_path:{rewrites}")

    # Critical pass: must finish + no tool failures + objective_complete.
    critical_pass = bool(finished and objective_complete and fail_n == 0 and det_fail_n == 0)

    overall_score = (
        0.30 * tool_accuracy
        + 0.30 * completeness
        + 0.20 * artifact_verification
        + 0.10 * step_efficiency
        + 0.10 * consistency
    )
    overall_score = max(0.0, min(1.0, float(overall_score)))

    return {
        "critical_pass": critical_pass,
        "overall_score": round(overall_score, 3),
        "dimensions": {
            "tool_accuracy": {"value": round(float(tool_accuracy), 3), "reasons": reasons["tool_accuracy"][:6]},
            "completeness": {"value": round(float(completeness), 3), "reasons": reasons["completeness"][:6]},
            "artifact_verification": {"value": round(float(artifact_verification), 3), "reasons": reasons["artifact_verification"][:6]},
            "step_efficiency": {"value": round(float(step_efficiency), 3), "reasons": reasons["step_efficiency"][:6]},
            "consistency": {"value": round(float(consistency), 3), "reasons": reasons["consistency"][:6]},
        },
        "counts": {
            "tool_ok": ok_n,
            "tool_fail": fail_n,
            "deterministic_fail": det_fail_n,
            "artifacts_total": artifacts_total,
        },
    }


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


def evaluate_outcome_structured(state: dict[str, Any]) -> dict[str, Any]:
    """
    Backward-compatible superset of evaluate_outcome: adds reason, improvement,
    confidence, metrics, and cost_score for planner / persistence hooks.
    """
    base = evaluate_outcome(state)
    from services.outcome_metrics import collect_outcome_metrics, heuristic_cost_score

    metrics = collect_outcome_metrics(state)
    refused = bool(state.get("refused"))
    success = bool(base.get("success")) and not refused
    issues = list(base.get("issues") or [])
    tf = int(base.get("tool_fail") or 0)

    if refused:
        reason = "refused"
        improvement = "Reframe the request or adjust governance; avoid repeat refusal triggers."
    elif tf > 0:
        reason = "tool_failed"
        first_issue = str(issues[0]) if issues else "check tool errors"
        improvement = f"Retry with a fallback or verify inputs ({first_issue})."
    elif not success:
        st = str(base.get("status") or "")
        if st != "finished":
            reason = st or "incomplete"
            improvement = "Extend runtime, simplify the goal, or verify model availability."
        else:
            reason = "evaluation_failed"
            improvement = "; ".join(str(x) for x in issues[:2]) if issues else "Review tool results and add verification."
    elif issues and any("no_tool_steps" in str(x) for x in issues):
        reason = "reply_only"
        improvement = "Add explicit read/verify steps when mutating files or running commands."
    else:
        reason = "ok"
        improvement = "Continue with the next plan slice or goal."

    conf_h = api_confidence_heuristic(state)
    confidence = float(conf_h.get("value") if isinstance(conf_h, dict) else 0.5)
    confidence = max(0.0, min(1.0, confidence))

    out: dict[str, Any] = {
        **base,
        "success": success,
        "reason": reason,
        "improvement": (improvement or "")[:500],
        "confidence": round(confidence, 3),
        "metrics": metrics,
        "cost_score": heuristic_cost_score(metrics, success),
    }
    # Deterministic validation matrix (optional). Kept separate from heuristic score.
    try:
        import runtime_safety

        if bool(runtime_safety.load_config().get("validation_matrix_enabled", True)):
            out["validation_matrix"] = evaluate_validation_matrix(state)
    except Exception:
        pass
    return out


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
