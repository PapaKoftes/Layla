"""CP-5 — one owner for the final user-visible answer text.

Before this, the user-visible answer was re-derived at each router reader from the run result: the
same `result["response"] or result["reply"]`, falling back to the last step's result (only when it is
a string — a raw tool-result dict must never be json.dumped into the reply), duplicated verbatim at
routers/agent.py (streamed + non-streamed). `answer_of` is that single owner.

Scope note (deliberate): this owns the USER-VISIBLE answer only. The finalizer's "last reasoned text"
(services/agent/run_finalizer.py) is a DIFFERENT value — the text the off-by-default answer-quality
assessment reads — and is intentionally not this. The two were once described as "two rules that
disagree about the answer"; they are actually two different measurements (delivered answer vs. reasoned
text), so the fix is to name the delivered answer once, here — not to force the assessment to read it.
"""
from __future__ import annotations

from typing import Any


def record_step(state: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    """Append one reasoning/tool step to the run's step log — the SINGLE write point (CP-6).

    Every ``state["steps"].append(...)`` routes through here so there is exactly one place that
    records a step (the signature-defect metric the architecture gate ratchets). Behaviour is
    identical to the raw append — the step dict passes through untouched — and ``state["steps"]`` is
    created if it does not exist yet. Returns the step for convenience.
    """
    state.setdefault("steps", []).append(step)
    return step


def answer_of(result: dict[str, Any]) -> str:
    """The final user-visible answer for a completed run.

    Prefers the run's synthesized prose answer (`response`/`reply`); falls back to the last step's
    result ONLY when that prose is empty AND the fallback is a string. Never returns a non-string, so a
    raw tool-result dict can never leak into the reply. Reproduces both router readers exactly.
    """
    if not isinstance(result, dict):
        return ""
    text = (result.get("response") or result.get("reply") or "").strip()
    if not text:
        steps = result.get("steps") or []
        final = steps[-1].get("result", "") if steps else ""
        if isinstance(final, str):
            text = final.strip()
    return text
