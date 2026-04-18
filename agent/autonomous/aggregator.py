from __future__ import annotations

from typing import Any

from autonomous.context import compress_tool_result
from autonomous.types import StepRecord


def _coerce_confidence(raw: object) -> str:
    s = str(raw or "").strip().lower()
    if s in ("low", "medium", "high"):
        return s
    return "medium"


def normalize_stopped_reason(raw: str) -> tuple[str, str | None]:
    """Map internal budget signals to a stable API contract."""
    r = str(raw or "").strip()
    if r in ("max_steps_loop_end", "max_steps_exceeded"):
        return "budget_exceeded", "steps"
    if r == "timeout_exceeded":
        return "budget_exceeded", "timeout"
    # Prefetch short-circuit reasons pass through unchanged
    return r, None


def aggregate_prefetch_hit(
    *,
    goal: str,
    value_gate: dict[str, Any],
    stopped_reason: str,
    prefetch_final: dict[str, Any],
    source: str,
    prefetch_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the same response shape as a full run when reuse/wiki prefetch matched."""
    meta = dict(prefetch_meta or {})
    trace_note = ""
    if source == "reuse":
        rid = meta.get("matched_run_id") or ""
        trace_note = f"Prefetched from investigation_reuse.jsonl (run_id={rid})"
    elif source == "wiki":
        wp = meta.get("wiki_path") or ""
        trace_note = f"Prefetched from wiki markdown ({wp})"
    elif source == "chroma":
        eid = meta.get("embedding_id") or ""
        ms = meta.get("match_score")
        trace_note = f"Prefetched from Chroma learnings (embedding_id={eid}, match_score={ms})"

    pf = dict(prefetch_final)
    if trace_note:
        pf["reasoning"] = trace_note[:2000]

    return aggregate(
        goal=goal,
        steps=[],
        value_gate=value_gate,
        stopped_reason=stopped_reason,
        prefetch_final=pf,
        files_accessed=None,
        final_override={
            "source": source,
            "reused": True,
            "prefetch_meta": meta,
        },
    )


def _confidence_model_base_score(label: str) -> int:
    """Numeric baseline so model 'high' maps above medium band without extra boosts."""
    return {"low": 2, "medium": 3, "high": 4}.get(label, 3)


def _score_to_confidence(score: int) -> str:
    if score <= 2:
        return "low"
    if score <= 3:
        return "medium"
    return "high"


def _derive_confidence(
    *,
    model_confidence: str,
    norm_stop: str,
    last_final: dict[str, Any] | None,
    findings_struct: list[dict[str, Any]],
    files_accessed: list[str] | None,
    tool_errors: list[str],
    steps: list[StepRecord],
) -> tuple[str, dict[str, Any]]:
    had_structured_final = bool(
        isinstance(last_final, dict)
        and not last_final.get("error")
        and (
            str(last_final.get("summary") or "").strip()
            or _normalize_findings_from_final(last_final)
            or str(last_final.get("reasoning") or "").strip()
        )
    )
    unique_files = len({p for p in (files_accessed or []) if str(p).strip()})
    evidence_backed = sum(
        1 for f in findings_struct if isinstance(f, dict) and (f.get("evidence") or [])
    )
    retry_extra = sum(max(0, (getattr(s.decision, "attempts_used", 1) or 1) - 1) for s in steps)
    budget_truncated = norm_stop == "budget_exceeded" and not had_structured_final

    score = _confidence_model_base_score(model_confidence)
    basis: dict[str, Any] = {
        "model_confidence": model_confidence,
        "unique_files_read": unique_files,
        "findings_with_evidence": evidence_backed,
        "budget_truncated": budget_truncated,
        "tool_error_count": len(tool_errors),
        "planner_extra_attempts": retry_extra,
    }

    if unique_files >= 3:
        score += 1
        basis["files_boost"] = True
    if evidence_backed >= 2:
        score += 1
        basis["evidence_boost"] = True
    if budget_truncated:
        score -= 1
        basis["budget_penalty"] = True
    if tool_errors:
        score -= 1
        basis["tool_error_penalty"] = True
    if retry_extra >= 2:
        score -= 1
        basis["retry_penalty"] = True
    if retry_extra >= 4:
        score -= 1
        basis["heavy_retry_penalty"] = True

    score = max(0, min(5, score))
    basis["score"] = score
    return _score_to_confidence(score), basis


def _normalize_findings_from_final(final: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(final, dict):
        return out
    raw = final.get("findings")
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            ev = item.get("evidence")
            ev_list: list[str] = []
            if isinstance(ev, list):
                ev_list = [str(x)[:500] for x in ev if x][:30]
            elif isinstance(ev, str) and ev.strip():
                ev_list = [ev.strip()[:500]]
            out.append(
                {
                    "insight": str(item.get("insight") or item.get("text") or "")[:4000],
                    "evidence": ev_list,
                }
            )
        elif isinstance(item, str) and item.strip():
            out.append({"insight": item.strip()[:4000], "evidence": []})
    return out


def _normalize_next_steps_from_final(final: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(final, dict):
        return out
    raw = final.get("next_steps")
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "action": str(item.get("action") or "")[:2000],
                "tool": str(item.get("tool") or "")[:120],
                "reason": str(item.get("reason") or "")[:2000],
                "confidence": _coerce_confidence(item.get("confidence")),
            }
        )
    return out[:40]


def build_investigation_trace(
    *,
    steps: list[StepRecord],
    findings_struct: list[dict[str, Any]],
    planner_reasoning: str,
    max_chars: int = 2800,
) -> str:
    """Compress run into steps + findings + short planner notes (UI-friendly)."""
    lines: list[str] = []
    step_n = 0
    for s in steps:
        if s.decision.type != "tool":
            continue
        step_n += 1
        tr = s.tool_result if isinstance(s.tool_result, dict) else {}
        hint = compress_tool_result(s.decision.tool, tr, max_chars=220)
        err = s.error or ""
        if err:
            hint = f"error: {err[:160]}"
        lines.append(f"{step_n}. {s.decision.tool}: {hint}")
    block_steps = "### Steps\n" + ("\n".join(lines) if lines else "(no tool steps)")

    findings_lines: list[str] = []
    for i, f in enumerate(findings_struct[:14], 1):
        if not isinstance(f, dict):
            continue
        ins = str(f.get("insight") or "")[:320].strip()
        if not ins:
            continue
        ev = f.get("evidence") if isinstance(f.get("evidence"), list) else []
        ev_s = ", ".join(str(x)[:120] for x in ev[:4] if x)
        suffix = f" — {ev_s}" if ev_s else ""
        findings_lines.append(f"{i}. {ins}{suffix}")

    block_findings = "### Findings\n" + ("\n".join(findings_lines) if findings_lines else "(none)")

    notes = ""
    pr = (planner_reasoning or "").strip()
    if pr:
        notes = "### Planner reasoning\n" + pr[:900] + ("…" if len(pr) > 900 else "")

    out = "\n\n".join(x for x in (block_steps, block_findings, notes) if x)
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out


def _fallback_findings_from_steps(steps: list[StepRecord]) -> list[dict[str, Any]]:
    """If planner did not emit structured final, derive short strings from tool summaries."""
    lines: list[str] = []
    for s in steps:
        tr = s.tool_result or {}
        if isinstance(tr, dict) and tr.get("ok") is not False:
            if s.decision.tool == "grep_code" and tr.get("matches"):
                lines.append(f"grep: {(str(tr.get('matches'))[:320])}")
            elif s.decision.tool == "read_file" and tr.get("content"):
                lines.append(f"read: partial content available ({len(str(tr.get('content')))} chars)")
    out: list[dict[str, Any]] = []
    for ln in lines[:25]:
        out.append({"insight": ln[:400], "evidence": []})
    return out


def aggregate(
    *,
    goal: str,
    steps: list[StepRecord],
    value_gate: dict[str, Any],
    stopped_reason: str,
    final_override: dict[str, Any] | None = None,
    wiki_candidates: list[dict[str, Any]] | None = None,
    files_accessed: list[str] | None = None,
    prefetch_final: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_errors: list[str] = []
    last_final: dict[str, Any] | None = prefetch_final if prefetch_final else None

    for s in steps:
        if s.error:
            tool_errors.append(str(s.error)[:500])
        if s.decision.type == "final" and isinstance(s.decision.final, dict):
            last_final = s.decision.final

    findings_struct = _normalize_findings_from_final(last_final)
    if not findings_struct:
        findings_struct = _fallback_findings_from_steps(steps)
    next_struct = _normalize_next_steps_from_final(last_final)

    summary = ""
    reasoning = ""
    model_conf = "medium"
    if isinstance(last_final, dict):
        summary = str(last_final.get("summary") or "")[:12000]
        reasoning = str(last_final.get("reasoning") or last_final.get("reasoning_summary") or "")[:12000]
        model_conf = _coerce_confidence(last_final.get("confidence"))

    norm_reason, budget_detail = normalize_stopped_reason(stopped_reason)
    investigation_trace = build_investigation_trace(
        steps=steps,
        findings_struct=findings_struct,
        planner_reasoning=reasoning,
    )
    trace_for_summary = investigation_trace.strip() or (reasoning[:2400] if reasoning else "")
    conf, confidence_basis = _derive_confidence(
        model_confidence=model_conf,
        norm_stop=norm_reason,
        last_final=last_final,
        findings_struct=findings_struct,
        files_accessed=list(files_accessed or []),
        tool_errors=tool_errors,
        steps=steps,
    )

    resp: dict[str, Any] = {
        "ok": True,
        "goal": goal,
        "value_gate": value_gate,
        "stopped_reason": norm_reason,
        "steps_used": len(steps),
        "summary": summary,
        "reasoning": reasoning or "",
        "investigation_trace": investigation_trace,
        "reasoning_summary": trace_for_summary[:2400] if trace_for_summary else "",
        "findings": findings_struct,
        "next_steps": next_struct,
        "proposed_actions": list(next_struct),
        "confidence": conf,
        "confidence_basis": confidence_basis,
        "tool_errors": tool_errors[-10:],
        "wiki_candidates": [],
        "files_accessed": list(files_accessed or [])[:200],
        "investigation_engine": True,
        "source": "fresh",
        "reused": False,
    }
    if budget_detail:
        resp["budget_detail"] = budget_detail
    if final_override:
        resp.update(final_override)
    if wiki_candidates:
        resp["wiki_candidates"] = wiki_candidates[:10]
    return resp
