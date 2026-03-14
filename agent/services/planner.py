"""
Lightweight planning engine: break complex goals into executable steps.
Uses LLM to produce a structured plan (3–6 steps); each step has task + suggested tools.
Supports agent roles: planner, executor, researcher, debugger, memory_curator.
"""
import json
import re
from typing import Any

ROLE_TOOL_HINTS = {
    "researcher": "Prefer: ddg_search, fetch_article, wiki_search, arxiv_search",
    "debugger": "Prefer: grep_code, python_ast, read_file, run_python",
    "memory_curator": "Prefer: search_memories, save_note, get_project_context",
}


def get_tool_reliability_hint() -> str:
    """Return hint string for tools with higher success rate (tool outcome learning)."""
    try:
        from layla.memory.db import get_tool_reliability
        stats = get_tool_reliability()
        if not stats:
            return ""
        # Top 3 by success_rate * avg_quality, min 5 outcomes
        ranked = [
            (name, s["success_rate"] * (s["avg_quality"] or 0.5))
            for name, s in stats.items()
            if s.get("count", 0) >= 3
        ]
        ranked.sort(key=lambda x: -x[1])
        top = [n for n, _ in ranked[:5] if n]
        if top:
            return f"Higher reliability (from past outcomes): {', '.join(top)}"
    except Exception:
        pass
    return ""

PLAN_KEYWORDS = frozenset(
    {"analyze", "build", "research", "investigate", "plan", "implement", "refactor", "audit"}
)
MIN_GOAL_LEN = 80


def should_plan(goal: str, cfg: dict | None = None, plan_depth: int = 0) -> bool:
    """True if goal warrants a structured plan (long or planning keywords). Respects max_plan_depth."""
    if cfg is not None and not cfg.get("planning_enabled", True):
        return False
    max_depth = int(cfg.get("max_plan_depth", 3)) if cfg else 3
    if plan_depth >= max_depth:
        return False
    g = (goal or "").strip().lower()
    if len(g) < MIN_GOAL_LEN:
        return False
    return any(kw in g for kw in PLAN_KEYWORDS)


def create_plan(goal: str, max_steps: int = 6, cfg: dict | None = None) -> list[dict]:
    """
    Use LLM to produce a structured plan.
    Each step: {"step": int, "task": str, "tools": list[str]}
    Limit to 3–6 steps.
    """
    if not goal or not goal.strip():
        return []
    try:
        from services.llm_gateway import run_completion
        tools_list = (
            "list_dir, read_file, grep_code, python_ast, security_scan, fetch_url, "
            "ddg_search, search_memories, write_file, apply_patch, workspace_map, "
            "project_discovery, fetch_article, wiki_search, arxiv_search"
        )
        skills_hint = ""
        try:
            from layla.skills.registry import get_skills_prompt_hint
            skills_hint = get_skills_prompt_hint(cfg)
        except Exception:
            pass
        reliability_hint = get_tool_reliability_hint()
        prompt = (
            f"Given this goal:\n\n{goal[:800]}\n\n"
            f"Produce a step-by-step plan. Output only a JSON array of objects. "
            f"Each object: {{\"step\": 1, \"task\": \"short description\", \"tools\": [\"tool1\", \"tool2\"]}}. "
            f"Use 3-6 steps. Choose tools from: {tools_list}. "
        )
        if reliability_hint:
            prompt += f"\n{reliability_hint}\n"
        if skills_hint:
            prompt += f"\n{skills_hint}\n"
        prompt += "Output only the JSON array, no other text."
        out = run_completion(prompt, max_tokens=400, temperature=0.2, stream=False)
        if not isinstance(out, dict):
            return []
        text = (
            (out.get("choices") or [{}])[0].get("message") or {}
        ).get("content", "") or (out.get("choices") or [{}])[0].get("text", "")
        if not text:
            return []
        m = re.search(r"\[[\s\S]*?\]", text)
        if not m:
            return []
        steps = json.loads(m.group(0))
        if not isinstance(steps, list):
            return []
        result = []
        for i, s in enumerate(steps[:max_steps]):
            if not isinstance(s, dict):
                continue
            task = (s.get("task") or s.get("description") or "").strip()
            tools = s.get("tools") or []
            if isinstance(tools, str):
                tools = [t.strip() for t in tools.split(",") if t.strip()]
            if not task:
                continue
            role = _infer_role(task)
            result.append({
                "step": i + 1,
                "task": task[:200],
                "tools": [str(t)[:60] for t in tools[:5]],
                "role": role,
            })
        return result[:6]
    except Exception:
        return []


def _infer_role(task: str) -> str:
    """Infer agent role from task keywords. Returns role name or empty string."""
    t = (task or "").lower()
    if any(k in t for k in ("research", "search", "find", "look up", "investigate", "wiki", "article")):
        return "researcher"
    if any(k in t for k in ("debug", "fix", "trace", "error", "bug", "inspect", "diagnose")):
        return "debugger"
    if any(k in t for k in ("remember", "save", "store", "recall", "memory", "context", "project")):
        return "memory_curator"
    return ""


def execute_plan(plan: list[dict], agent_run_fn: Any, goal_prefix: str = "", plan_depth: int = 0, **agent_kwargs: Any) -> dict:
    """
    Execute each plan step sequentially via agent_run_fn(step_goal, ...).
    agent_run_fn is autonomous_run or a compatible callable.
    plan_depth: current planning depth; steps run at plan_depth+1 to respect max_plan_depth.
    agent_kwargs: context, workspace_root, allow_write, allow_run, etc. (forwarded from caller)
    Returns combined result with steps executed and final summary.
    """
    if not plan:
        return {"status": "no_plan", "steps_done": [], "summary": ""}
    defaults = {
        "context": "",
        "workspace_root": "",
        "allow_write": False,
        "allow_run": False,
        "conversation_history": [],
        "aspect_id": "morrigan",
        "show_thinking": False,
    }
    defaults.update(agent_kwargs)
    defaults["plan_depth"] = plan_depth + 1  # enforce depth increment; agent_kwargs must not override
    steps_done = []
    for s in plan:
        task = s.get("task", "")
        tools_hint = s.get("tools", [])
        role = s.get("role", "")
        step_goal = task
        if tools_hint:
            step_goal += f" (consider: {', '.join(tools_hint[:3])})"
        if role and role in ROLE_TOOL_HINTS:
            step_goal += f" [{ROLE_TOOL_HINTS[role]}]"
        if goal_prefix:
            step_goal = f"{goal_prefix}\n\nStep {s.get('step', len(steps_done)+1)}: {step_goal}"
        try:
            result = agent_run_fn(step_goal, **defaults)
            steps_done.append({
                "step": s.get("step"),
                "task": task,
                "result_status": result.get("status", ""),
            })
        except Exception as e:
            steps_done.append({"step": s.get("step"), "task": task, "result_status": "error", "error": str(e)})
    summary = "\n".join(f"{d.get('step')}. {d.get('task')}: {d.get('result_status', '')}" for d in steps_done)
    return {"status": "plan_completed", "steps_done": steps_done, "summary": summary}
