"""
Bounded recovery hints for governed plan steps (text-only nudges; never widens allow_write/allow_run).

When autonomy_optimizer_enabled, failed step validation can suggest one alternate tool
already allowed by the step allowlist, or a generic retry rationale.
"""
from __future__ import annotations

from typing import Any

# Prefer read/verify-class tools after mutating or risky tools fail.
_FALLBACKS: dict[str, tuple[str, ...]] = {
    "write_file": ("read_file", "grep_code", "list_dir"),
    "write_files_batch": ("read_file", "list_dir"),
    "apply_patch": ("read_file", "grep_code"),
    "shell": ("read_file", "grep_code"),
    "run_python": ("read_file",),
    "run_tests": ("read_file", "grep_code"),
}


def _normalize_allowlist(raw: list[Any] | None) -> frozenset[str] | None:
    if not raw or not isinstance(raw, list):
        return None
    names = {str(t).strip() for t in raw if str(t).strip()}
    return frozenset(names) if names else None


def propose_step_recovery(
    *,
    failed_tool: str,
    validation_reason: str,
    step_tools: list[Any] | None,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """
    Return a single recovery proposal. Suggested tools are always drawn from step_tools
    when that allowlist is non-empty, so governance cannot widen the step tool surface.
    """
    if not bool(cfg.get("autonomy_optimizer_enabled", False)):
        return {"action": "none"}
    ft = (failed_tool or "").strip()
    allow = _normalize_allowlist(step_tools)
    cands = list(_FALLBACKS.get(ft, ("read_file", "grep_code")))
    pick = ""
    if allow is not None:
        for c in cands:
            if c in allow:
                pick = c
                break
        if not pick:
            for a in sorted(allow):
                if a not in ("reason", "think", "none") and a != ft:
                    pick = a
                    break
    else:
        pick = cands[0] if cands else ""

    vr = (validation_reason or "").strip()[:160]
    if pick and pick != ft:
        return {
            "action": "suggest_tool",
            "tool": pick,
            "rationale": f"validation:{vr or 'failed'} — use `{pick}` before repeating `{ft}`.".strip(),
        }
    return {
        "action": "retry",
        "rationale": f"validation:{vr or 'failed'} — retry with a narrower goal or explicit file path.".strip(),
    }


def last_failed_tool_from_agent_response(resp: dict[str, Any]) -> str:
    st = resp.get("state") if isinstance(resp.get("state"), dict) else {}
    raw_steps = st.get("steps") or []
    if not isinstance(raw_steps, list):
        return ""
    for entry in reversed(raw_steps):
        if not isinstance(entry, dict):
            continue
        act = str(entry.get("action") or "").strip()
        if act in ("reason", "think", "client_abort", "none", ""):
            continue
        r = entry.get("result")
        if isinstance(r, dict) and r.get("ok") is False:
            return act
    return ""
