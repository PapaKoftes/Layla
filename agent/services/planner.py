"""
Lightweight planning engine: break complex goals into executable steps.
Uses LLM to produce a structured plan (3–6 steps); each step has task + suggested tools.
"""
import json
import re
from typing import Any

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


def create_plan(goal: str, max_steps: int = 6) -> list[dict]:
    """
    Use LLM to produce a structured plan.
    Each step: {"step": int, "task": str, "tools": list[str]}
    Limit to 3–6 steps.
    """
    if not goal or not goal.strip():
        return []
    try:
        from services.llm_gateway import run_completion
        prompt = (
            f"Given this goal:\n\n{goal[:800]}\n\n"
            f"Produce a step-by-step plan. Output only a JSON array of objects. "
            f"Each object: {{\"step\": 1, \"task\": \"short description\", \"tools\": [\"tool1\", \"tool2\"]}}. "
            f"Use 3-6 steps. Choose tools from: list_dir, read_file, grep_code, python_ast, "
            "security_scan, fetch_url, ddg_search, search_memories, write_file, apply_patch. "
            "Output only the JSON array, no other text."
        )
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
            result.append({
                "step": i + 1,
                "task": task[:200],
                "tools": [str(t)[:60] for t in tools[:5]],
            })
        return result[:6]
    except Exception:
        return []


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
        step_goal = task
        if tools_hint:
            step_goal += f" (consider: {', '.join(tools_hint[:3])})"
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
