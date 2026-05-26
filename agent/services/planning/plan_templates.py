"""
Rule-based plan skeletons (system-first planning). LLM fills only steps marked open=True when plan_llm_gap_fill_only.
"""
from __future__ import annotations

import json
import re
from typing import Any

from services.llm_gateway import run_completion


def match_skeleton_plan(goal: str, cfg: dict | None) -> list[dict] | None:
    """
    Return a closed template plan or None. No LLM.
    Respects plan_system_first_enabled.
    """
    if not cfg or not cfg.get("plan_system_first_enabled"):
        return None
    g = (goal or "").strip().lower()
    if len(g) < 40:
        return None

    if re.search(r"\b(fix|debug|repair)\b.*\b(test|pytest|failing)\b|\b(test|pytest)\b.*\b(fix|fail)\b", g):
        return [
            {"step": 1, "task": "Locate failing tests and error output", "tools": ["grep_code", "read_file", "run_tests"], "role": "debugger"},
            {"step": 2, "task": "Identify root cause in source", "tools": ["read_file", "grep_code", "python_ast"], "role": "debugger"},
            {"step": 3, "task": "Apply minimal fix and re-run tests", "tools": ["apply_patch", "run_tests"], "role": "edit"},
        ]

    if any(k in g for k in ("refactor", "restructure", "clean up")) and ("file" in g or "module" in g):
        return [
            {"step": 1, "task": "Map symbols and call sites", "tools": ["grep_code", "read_file", "list_dir"], "role": "analysis"},
            {"step": 2, "task": "Plan incremental edits with checkpoints", "tools": ["read_file", "git_diff"], "role": "planning"},
            {"step": 3, "task": "Execute edits and verify", "tools": ["apply_patch", "run_tests"], "role": "edit"},
        ]

    if any(k in g for k in ("research", "investigate", "compare", "survey")):
        return [
            {"step": 1, "task": "Gather external and internal references", "tools": ["ddg_search", "read_file", "grep_code"], "role": "researcher"},
            {"step": 2, "task": "Synthesize findings vs project context", "tools": ["read_file", "search_memories"], "role": "researcher"},
            {"step": 3, "task": "Deliver concise summary and next actions", "tools": ["read_file"], "role": "analysis"},
        ]

    return None


def skeleton_with_open_slots(goal: str, cfg: dict | None) -> list[dict] | None:
    """Template with one OPEN step for LLM gap-fill when plan_llm_gap_fill_only."""
    if not cfg or not cfg.get("plan_system_first_enabled"):
        return None
    if not cfg.get("plan_llm_gap_fill_only"):
        return None
    g = (goal or "").strip().lower()
    if len(g) < 60:
        return None
    if not any(k in g for k in PLAN_KEYWORDS_FALLBACK):
        return None
    return [
        {"step": 1, "task": "Survey repository layout and constraints", "tools": ["list_dir", "read_file", "grep_code"], "role": "analysis", "open": False},
        {"step": 2, "task": "OPEN: Specialist analysis for this goal", "tools": [], "role": "analysis", "open": True},
        {"step": 3, "task": "Verification and handoff", "tools": ["read_file", "run_tests"], "role": "test", "open": False},
    ]


PLAN_KEYWORDS_FALLBACK = frozenset(
    {"analyze", "build", "research", "investigate", "plan", "implement", "refactor", "audit", "design"}
)


def fill_open_plan_steps(goal: str, plan: list[dict], max_steps: int = 6) -> list[dict]:
    """Call LLM only for rows with open=True; replace task/tools from model output."""
    open_idx = [i for i, s in enumerate(plan) if isinstance(s, dict) and s.get("open")]
    if not open_idx:
        return plan
    try:
        prompt = (
            f"Goal:\n{goal[:900]}\n\n"
            "Fill ONLY the open plan step(s). Return JSON array of same length as open steps, "
            'each object: {"task": "...", "tools": ["tool1"]}. '
            "Use short tasks. Tools must be from Layla registry names.\n"
            f"Open step indices: {open_idx}\n"
            "Output only the JSON array."
        )
        out = run_completion(prompt, max_tokens=300, temperature=0.15, stream=False)
        if not isinstance(out, dict):
            return plan
        text = (
            (out.get("choices") or [{}])[0].get("message") or {}
        ).get("content", "") or (out.get("choices") or [{}])[0].get("text", "")
        m = re.search(r"\[[\s\S]*?\]", text or "")
        if not m:
            return plan
        fills = json.loads(m.group(0))
        if not isinstance(fills, list):
            return plan
        fi = 0
        for i in open_idx:
            if fi >= len(fills):
                break
            patch = fills[fi]
            fi += 1
            if not isinstance(patch, dict):
                continue
            row = plan[i]
            t = (patch.get("task") or "").strip()
            if t:
                row["task"] = t[:220]
            tl = patch.get("tools")
            if isinstance(tl, list) and tl:
                row["tools"] = [str(x)[:60] for x in tl[:5]]
            row.pop("open", None)
        return plan[:max_steps]
    except Exception:
        return plan
