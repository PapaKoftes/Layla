"""
Optional one-line inline suggestion appended to the assistant reply (North Star initiative, gated).
No extra LLM call. Default off: config inline_initiative_enabled.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def maybe_append_inline_suggestion(text: str, state: dict[str, Any], cfg: dict[str, Any]) -> str:
    if not text or not isinstance(text, str):
        return text if isinstance(text, str) else ""
    if not bool(cfg.get("inline_initiative_enabled", False)) and not bool(
        cfg.get("initiative_engine_enabled", False)
    ):
        return text
    if state.get("refused"):
        return text
    steps = state.get("steps") or []
    tool_steps = [s for s in steps if s.get("action") and s["action"] not in ("reason", "think", "client_abort")]
    _min_tools = 1 if bool(cfg.get("initiative_engine_enabled", False)) else 2
    if len(tool_steps) < _min_tools:
        return text
    goal = (state.get("original_goal") or state.get("objective") or "").lower()
    suggestion = ""

    # State-aware triggers (§10/14): fabrication workflow, repetition, multi-step, weak outcome
    fab_kw = ("dxf", "toolpath", "toolpaths", "g-code", "gcode", "cam", "machining", "nc program")
    if any(k in goal for k in fab_kw) and len(tool_steps) >= 2:
        suggestion = (
            "Next: if you are converting DXF→machine motion, batch geometry_extract_machining_ir (or equivalent) "
            "before post/G-code, and sanity-check units/stock once for the whole batch."
        )
    if not suggestion:
        actions = [str(s.get("action") or "") for s in tool_steps if s.get("action")]
        top_action, top_n = Counter(actions).most_common(1)[0] if actions else ("", 0)
        if top_n >= 2 and top_action and top_action not in ("reason", "think", "none"):
            suggestion = (
                f"Next: you used `{top_action}` repeatedly — consider a helper script, batch op, or one read that "
                "covers all targets instead of the same call pattern."
            )
    if not suggestion and len(tool_steps) >= 3:
        suggestion = (
            "Next: checkpoint — restate the sub-goal for this multi-step workflow and confirm the last tool "
            "results match before adding more steps."
        )
    if bool(cfg.get("initiative_engine_enabled", False)):
        try:
            from services.initiative_engine import collect_initiative_hints

            eng_hints = collect_initiative_hints(state, cfg)
            if eng_hints:
                extra = eng_hints[0]
                suggestion = (suggestion + " " + extra).strip() if suggestion else extra
        except Exception:
            pass
    if not suggestion:
        try:
            from services.outcome_evaluation import evaluate_outcome

            _probe = {**state, "status": "finished"}
            ev = evaluate_outcome(_probe)
            sc = float(ev.get("score") or 1.0)
            if sc < 0.55 or int(ev.get("tool_fail") or 0) >= 1:
                suggestion = (
                    "Next: outcome looks fragile — add a read/verify step (read_file, grep_code, or a narrow test) "
                    "before more writes or runs."
                )
        except Exception:
            pass

    if not suggestion:
        if any(k in goal for k in ("test", "pytest", "unittest")):
            suggestion = "Next: run the narrowest test command you can (e.g. pytest path::test -q) to confirm behavior."
        elif any(k in goal for k in ("doc", "readme", "comment")):
            suggestion = "Next: add or update a short docstring or README section for the surface you changed."
        elif any(k in goal for k in ("refactor", "clean", "lint")):
            suggestion = "Next: run lint on touched files and fix any new issues before expanding scope."
        else:
            suggestion = "Next: verify the change with read_file or a quick grep for call sites you may have missed."

    codex_warm = False
    wp = (state.get("workspace_root") or "").strip()
    if wp and bool(cfg.get("relationship_codex_inject_enabled", False)):
        try:
            from pathlib import Path

            from layla.tools.registry import inside_sandbox
            from services.relationship_codex import codex_has_entities, load_codex

            wrp = Path(wp).expanduser().resolve()
            if wrp.is_dir() and inside_sandbox(wrp) and codex_has_entities(load_codex(wrp)):
                codex_warm = True
        except Exception:
            pass
    if suggestion and codex_warm:
        suggestion = (
            "Given people/context in your relationship codex — "
            + suggestion
            + " If someone’s role or preferences shifted, update Workspace → Codex."
        )

    if not suggestion:
        return text
    if "\n\n—\n*Suggestion:*" in text or "*Suggestion:*" in text:
        return text
    try:
        if bool(cfg.get("initiative_ledger_enabled", True)):
            from layla.memory.db import add_initiative_suggestion

            add_initiative_suggestion(str(state.get("conversation_id") or ""), suggestion)
    except Exception:
        pass
    return text.rstrip() + f"\n\n—\n*Suggestion:* {suggestion}"
