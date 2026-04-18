from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from autonomous.types import PlannerDecision
from services.llm_gateway import run_completion

_JSON_OBJ = re.compile(r"\{[\s\S]*\}")


def _extract_json_obj(text: str) -> dict[str, Any] | None:
    m = _JSON_OBJ.search(text or "")
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _validate_decision(obj: dict[str, Any], allowlist: list[str]) -> str | None:
    """Return error message or None if OK."""
    t = str(obj.get("type") or "").strip().lower()
    if t not in ("tool", "final"):
        return "invalid_type"
    if t == "final":
        if not isinstance(obj.get("final"), dict):
            return "final_must_be_object"
        return None
    tool = str(obj.get("tool") or "").strip()
    if not tool:
        return "missing_tool"
    if tool not in allowlist:
        return "tool_not_in_allowlist"
    if not isinstance(obj.get("args"), dict):
        return "args_must_be_object"
    return None


@dataclass
class Planner:
    tool_allowlist: list[str]

    def decide(self, *, goal: str, context: dict[str, Any], budget_hint: str) -> PlannerDecision:
        """Plan one step: retry once on invalid JSON/shape."""
        allow = ", ".join(self.tool_allowlist)
        base = (
            "You are a constrained INVESTIGATION planner (read-only tools).\n"
            "You must ONLY output a single JSON object. No markdown fences.\n"
            "Allowed tools (never invent names):\n"
            f"{allow}\n\n"
            f"BUDGET:\n{budget_hint}\n\n"
            f"GOAL:\n{goal[:1500]}\n\n"
            f"CONTEXT:\n{json.dumps(context, ensure_ascii=False)[:6000]}\n\n"
            "Avoid redundant read_file calls — check files_read_this_run and TOOL CACHE in context.\n"
            "Prefer grep_code / search_codebase for symbols before reading whole files.\n\n"
            "Output JSON schema:\n"
            '{"type":"tool"|"final","tool":"<tool_name>","args":{},"final":{}}\n'
            "Rules:\n"
            '- type "final": set "final" to { "summary": "...", "reasoning": "...", '
            '"findings": [{"insight":"...","evidence":["path:line"]}], '
            '"next_steps": [{"action":"...","tool":"write_file","reason":"...","confidence":"high|medium|low"}], '
            '"confidence": "low|medium|high" }\n'
            '- type "tool": include tool + args only.\n'
            "- Prefer fewer, higher-signal tool calls.\n"
            "- Never invent tools.\n"
        )
        err_prev = ""
        for attempt in range(2):
            correction = ""
            if attempt == 1:
                correction = (
                    "\nYour previous output was invalid. Fix it.\n"
                    f"Previous error hint: {err_prev}\n"
                    "Reply with ONE valid JSON object only.\n"
                )
            out = run_completion(base + correction, max_tokens=320, temperature=0.12, stream=False)
            text = ""
            try:
                text = (
                    ((out.get("choices") or [{}])[0].get("message") or {}).get("content")
                    or (out.get("choices") or [{}])[0].get("text")
                    or ""
                )
            except Exception:
                text = ""
            obj = _extract_json_obj(text)
            if not obj:
                err_prev = "planner_parse_failed"
                continue
            verr = _validate_decision(obj, self.tool_allowlist)
            if verr:
                err_prev = verr
                continue
            t = str(obj.get("type") or "").strip().lower()
            tool = str(obj.get("tool") or "").strip()
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
            final = obj.get("final") if isinstance(obj.get("final"), dict) else {}
            au = attempt + 1
            if t == "final":
                return PlannerDecision(
                    type="final", final=final or {"summary": (text or "").strip()[:1200]}, attempts_used=au
                )
            if t == "tool" and tool not in self.tool_allowlist:
                return PlannerDecision(
                    type="final", final={"error": "tool_not_allowed", "tool": tool}, attempts_used=au
                )
            return PlannerDecision(type="tool", tool=tool, args=args, final={}, attempts_used=au)
        return PlannerDecision(
            type="final",
            final={"error": "planner_failed_after_retry", "raw": "invalid planner JSON after 2 attempts"},
            attempts_used=2,
        )
