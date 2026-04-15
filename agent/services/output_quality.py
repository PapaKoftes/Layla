"""Deterministic output quality gate (no extra LLM calls)."""

from __future__ import annotations

import re
from typing import Any

_CODE_FENCE = re.compile(r"```")
_JSON_START = re.compile(r"^\s*[\[{]")

_HEDGE_PATTERNS = [
    re.compile(r"^\s*(sure|of course)[,\.\!\s]+", re.I),
    re.compile(r"^\s*(here'?s|here is)\s+", re.I),
    re.compile(r"^\s*(i think|i believe|it seems|it looks like)[,\s]+", re.I),
    re.compile(r"^\s*as an ai( language model)?[,\s]+", re.I),
]


def _looks_structured(text: str) -> bool:
    if not text:
        return False
    if _CODE_FENCE.search(text):
        return True
    if _JSON_START.match(text):
        return True
    return False


def _dedupe_paragraphs(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        k = re.sub(r"\s+", " ", p).strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return "\n\n".join(out)


def clean_output(text: str, cfg: dict[str, Any] | None = None) -> str:
    """Light cleanup: strip common hedges, collapse repetition, preserve code/JSON."""
    if not text:
        return ""
    if _looks_structured(text):
        return text.strip()
    t = (text or "").strip()
    if not t:
        return ""

    # Strip leading hedges per paragraph (one pass each pattern)
    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    cleaned: list[str] = []
    for p in paras:
        pp = p
        for rx in _HEDGE_PATTERNS:
            pp2 = rx.sub("", pp, count=1).strip()
            pp = pp2 if pp2 else pp
        cleaned.append(pp)
    t = "\n\n".join([p for p in cleaned if p.strip()])

    # Normalize excessive blank lines
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    # Minimal repetition control (exact / near-exact paragraphs)
    t = _dedupe_paragraphs(t)
    return t.strip()


def passes_completion_gate(
    *,
    goal: str,
    text: str,
    state: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """
    Strict deterministic completion gate.
    Returns (ok, reasons_failed).
    """
    reasons: list[str] = []
    t = (text or "").strip()
    g = (goal or "").strip()
    if not t:
        reasons.append("empty_response")
    if len(t) < 20:
        reasons.append("too_short")

    # Prevent pure restatement (rough Jaccard token similarity).
    def _tok(s: str) -> set[str]:
        s = re.sub(r"[^a-zA-Z0-9_ ]+", " ", (s or "").lower())
        parts = [p for p in s.split() if len(p) >= 3]
        return set(parts[:500])

    gt = _tok(g)
    tt = _tok(t)
    if gt and tt:
        inter = len(gt & tt)
        union = len(gt | tt)
        sim = inter / float(union or 1)
        if sim >= 0.70:
            reasons.append(f"restates_goal(sim={sim:.2f})")

    # If tools were used, require at least one successful tool result.
    st = state or {}
    tool_calls = int(st.get("tool_calls") or 0)
    if tool_calls > 0:
        steps = st.get("steps") or []
        ok_tool = False
        for s in steps:
            if not isinstance(s, dict):
                continue
            act = s.get("action")
            if not act or act in ("reason", "think", "none", "client_abort", "pre_read_probe", "completion_gate"):
                continue
            r = s.get("result")
            if isinstance(r, dict) and r.get("ok"):
                ok_tool = True
                break
        if not ok_tool:
            reasons.append("no_successful_tool_steps")

    try:
        if bool((cfg or {}).get("completion_gate_block_structured_json", True)):
            # Avoid accidentally returning decision JSON blobs.
            if t.startswith("{") and "\"action\"" in t[:200]:
                reasons.append("looks_like_decision_json")
    except Exception:
        pass

    return (len(reasons) == 0), reasons

