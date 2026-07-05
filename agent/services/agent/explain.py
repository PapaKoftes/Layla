"""Explainable reasoning mode (BL-237) — a concise, human-readable "why".

Distinct from raw chain-of-thought: this distils a run's existing trace (the `think`
steps, the tool sequence + outcomes, the final answer) into a short structured
rationale a human can skim — "here's what I concluded and why", not the full thinking
tokens. Deterministic (no extra model call), so it's cheap and always available; the
run-integration in `run_finalizer` is flag-gated (`explainable_reasoning_enabled`).
"""
from __future__ import annotations

from typing import Any

_BOOKKEEPING = {"none", "client_abort", "think", "reason", "finish", "wakeup"}


def _step_ok(step: dict) -> bool | None:
    r = step.get("result")
    if isinstance(r, dict) and "ok" in r:
        return bool(r["ok"])
    return None


def build_explanation(
    steps: list[dict],
    *,
    goal: str = "",
    answer: str = "",
    max_thoughts: int = 5,
    max_tools: int = 12,
) -> dict[str, Any]:
    """Distil a run trace into a structured + markdown rationale."""
    steps = steps or []
    thoughts: list[str] = []
    tools: list[dict] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        action = str(s.get("action") or "")
        if action == "think":
            t = (s.get("result") or {}).get("thought") if isinstance(s.get("result"), dict) else None
            if t:
                thoughts.append(str(t).strip())
        elif action and action not in _BOOKKEEPING:
            tools.append({"tool": action, "ok": _step_ok(s)})

    key_thoughts = thoughts[:max_thoughts]
    tool_summary = tools[:max_tools]
    n_ok = sum(1 for t in tools if t["ok"] is True)
    n_fail = sum(1 for t in tools if t["ok"] is False)

    # markdown "why"
    lines: list[str] = []
    if goal:
        lines.append(f"**Goal:** {goal.strip()[:300]}")
    if key_thoughts:
        lines.append("**Reasoning:**")
        lines.extend(f"- {t[:240]}" for t in key_thoughts)
    if tool_summary:
        seq = " → ".join(
            f"{t['tool']}{'✓' if t['ok'] else ('✗' if t['ok'] is False else '')}" for t in tool_summary
        )
        lines.append(f"**Actions taken:** {seq}")
        if n_fail:
            lines.append(f"_({n_ok} succeeded, {n_fail} failed)_")
    if answer:
        lines.append(f"**Conclusion:** {answer.strip()[:400]}")
    if not lines:
        lines.append("_No reasoning trace was recorded for this run._")

    return {
        "goal": goal,
        "thoughts": key_thoughts,
        "tools": tool_summary,
        "tools_succeeded": n_ok,
        "tools_failed": n_fail,
        "answer": answer,
        "markdown": "\n".join(lines),
    }


def explain_state(state: dict, *, answer: str = "") -> dict[str, Any]:
    """Convenience wrapper: pull goal + steps (+ optionally the answer) from a run state."""
    state = state or {}
    ans = answer or ""
    if not ans:
        for s in reversed(state.get("steps") or []):
            if isinstance(s, dict) and s.get("action") == "reason":
                r = s.get("result")
                ans = r if isinstance(r, str) else ""
                if ans:
                    break
    return build_explanation(
        state.get("steps") or [],
        goal=state.get("original_goal") or state.get("objective") or "",
        answer=ans,
    )
