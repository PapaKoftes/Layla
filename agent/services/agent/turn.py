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
        last = steps[-1] if steps and isinstance(steps[-1], dict) else {}
        final = last.get("result", "")
        if isinstance(final, str):
            text = final.strip()
        elif isinstance(final, dict) and final.get("reason") == "approval_required":
            # A turn that ends on a queued approval has no prose; the router then fell back to the generic
            # "Ready. What do you need?" standby (seen live) — the operator was never told anything waits.
            text = approval_waiting_message(last)
    return text


def tool_result_fallback(steps: list | None) -> str:
    """A truthful reply built from what a tool returned, for a turn whose model reply came out empty.

    Live, list_dir succeeded but the model's reply was only a raw JSON dump, so the operator got the
    generic standby. Only results that render unambiguously are used; otherwise "" (caller's standby).
    """
    for s in reversed(steps or []):
        if not isinstance(s, dict) or s.get("action") != "list_dir":
            continue
        r = s.get("result") if isinstance(s.get("result"), dict) else {}
        entries = r.get("entries")
        if not r.get("ok") or not isinstance(entries, list):
            continue
        names = [f"{e.get('name')}/" if e.get("type") == "dir" else str(e.get("name"))
                 for e in entries if isinstance(e, dict) and e.get("name")]
        return ("That folder is empty." if not names
                else "Here's what's in that folder:\n" + "\n".join(f"- {n}" for n in names[:200]))
    return ""


UNWRITTEN_NOTE ="Note: no file was written in this turn — nothing was created or changed on disk."


def with_write_honesty(text: str, operator_message: str, steps: list | None) -> str:
    """Append a plain note when the operator asked to create a file and no write ran or is awaiting approval.

    Live on jinx-20b a create-file turn produced only a code block plus "File created." while nothing was
    written. This doesn't parse the reply (no false positives on prose): it compares what was ASKED with what
    the turn's steps actually DID.
    """
    if not (text or "").strip():
        return text
    try:
        from services.agent.forced_tool import _wants_new_file

        if not _wants_new_file((operator_message or "").strip()):
            return text
    except Exception:
        return text
    for s in steps or []:
        if not isinstance(s, dict) or s.get("action") not in ("write_file", "write_files_batch", "apply_patch", "replace_in_file"):
            continue
        r = s.get("result") if isinstance(s.get("result"), dict) else {}
        if r.get("ok") or r.get("reason") == "approval_required":
            return text
    return text.rstrip() + "\n\n" + UNWRITTEN_NOTE


def approval_waiting_message(step: dict[str, Any]) -> str:
    """Plain words for "this tool call is waiting for your approval" (names the tool and its target)."""
    step = step if isinstance(step, dict) else {}
    res = step.get("result") if isinstance(step.get("result"), dict) else {}
    tool = str(step.get("action") or res.get("tool") or "that action")
    args = step.get("args") if isinstance(step.get("args"), dict) else (res.get("args") if isinstance(res.get("args"), dict) else {})
    target = str(args.get("path") or args.get("file") or args.get("command") or "").strip()
    what = f"{tool} on {target}" if target else tool
    return f"I need your approval before I run {what}. It's waiting for you under Approvals."
