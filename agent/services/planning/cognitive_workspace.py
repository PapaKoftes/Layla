"""
Cognitive workspace (deliberation workspace / tree-of-thought reasoning).

Problem → Generate multiple approaches → Evaluate → Choose best

Instead of linear reasoning, Layla generates several strategies, evaluates which is most
promising, then executes with the chosen approach. Multiplies intelligence with the same model.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("layla")

# Canonical approaches: search-first, reasoning-first, tool-first
APPROACHES = {
    "search": {
        "name": "Search-first",
        "description": "Gather context first: workspace_map, search_memories, ddg_search. Build a picture before reasoning.",
        "bias": "Prefer search and discovery tools before deep analysis. Use workspace_map, search_memories, ddg_search early.",
    },
    "reasoning": {
        "name": "Reasoning-first",
        "description": "Deep chain-of-thought reasoning. Think through the problem carefully before using tools.",
        "bias": "Reason step-by-step. Use tools only when you need specific data. Minimize tool calls until you have a clear hypothesis.",
    },
    "tools": {
        "name": "Tool-first",
        "description": "Explore immediately: read_file, grep_code, list_dir. Let the codebase and files guide reasoning.",
        "bias": "Start with read_file, list_dir, grep_code to explore. Let what you find shape your reasoning.",
    },
}


def _generate_approaches(goal: str) -> list[dict[str, Any]]:
    """Generate 3 candidate approaches for the goal. Uses LLM when available."""
    try:
        from services.llm.llm_gateway import run_completion
        prompt = (
            f"Goal: {goal[:500]}\n\n"
            "Three possible approaches:\n"
            "A) Search-first: gather context (workspace_map, search_memories, web search) before reasoning\n"
            "B) Reasoning-first: deep chain-of-thought, use tools only when needed\n"
            "C) Tool-first: explore codebase/files immediately (read_file, grep_code, list_dir)\n\n"
            "Output JSON: {\"approaches\": [{\"id\": \"A\", \"name\": \"Search-first\", \"brief\": \"one line\"}, ...]}"
        )
        out = run_completion(prompt, max_tokens=300, temperature=0.3, stream=False)
        if isinstance(out, dict):
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
            if text:
                m = re.search(r"\{[\s\S]*?\}", text)
                if m:
                    data = json.loads(m.group(0))
                    approaches = data.get("approaches", [])
                    if len(approaches) >= 2:
                        return approaches[:3]
    except Exception as e:
        logger.debug("cognitive_workspace generate failed: %s", e)
    # Fallback: return canonical approaches
    return [
        {"id": "A", "name": "Search-first", "brief": "Gather context before reasoning", "key": "search"},
        {"id": "B", "name": "Reasoning-first", "brief": "Deep thinking before tools", "key": "reasoning"},
        {"id": "C", "name": "Tool-first", "brief": "Explore codebase immediately", "key": "tools"},
    ]


def _evaluate_approaches(goal: str, approaches: list[dict]) -> dict[str, Any]:
    """Evaluate which approach is most promising. Returns {chosen_id, chosen_key, rationale}."""
    try:
        from services.llm.llm_gateway import run_completion
        approaches_str = "\n".join(
            f"{a.get('id','')}) {a.get('name','')}: {a.get('brief','')}" for a in approaches[:3]
        )
        prompt = (
            f"Goal: {goal[:400]}\n\n"
            f"Approaches:\n{approaches_str}\n\n"
            "Which approach is most promising? Output JSON: {\"chosen\": \"A\" or \"B\" or \"C\", \"rationale\": \"one sentence\"}"
        )
        out = run_completion(prompt, max_tokens=150, temperature=0.1, stream=False)
        if isinstance(out, dict):
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
            if text:
                m = re.search(r"\{[\s\S]*?\}", text)
                if m:
                    data = json.loads(m.group(0))
                    chosen = (data.get("chosen") or "B").strip().upper()
                    rationale = (data.get("rationale") or "")[:200]
                    # Map A/B/C to key
                    id_to_key = {a.get("id", "").upper(): a.get("key", "reasoning") for a in approaches}
                    key = id_to_key.get(chosen, "reasoning")
                    return {"chosen_id": chosen, "chosen_key": key, "rationale": rationale}
    except Exception as e:
        logger.debug("cognitive_workspace evaluate failed: %s", e)
    return {"chosen_id": "B", "chosen_key": "reasoning", "rationale": "Default: reasoning-first"}


def run_deliberation(goal: str, context: str = "") -> dict[str, Any]:
    """
    Run cognitive workspace: generate approaches → evaluate → choose best.
    Returns {chosen_key, rationale, strategy_hint, approaches}.
    """
    if not (goal or "").strip():
        return {"chosen_key": "reasoning", "rationale": "", "strategy_hint": "", "approaches": []}
    approaches = _generate_approaches(goal)
    result = _evaluate_approaches(goal, approaches)
    chosen_key = result.get("chosen_key", "reasoning")
    rationale = result.get("rationale", "")
    approach_def = APPROACHES.get(chosen_key, APPROACHES["reasoning"])
    strategy_hint = approach_def.get("bias", "")
    chosen_name = approach_def.get("name", "Reasoning-first")

    # BL-235: persist the decision — chosen + rationale + rejected alternatives — so
    # a later turn can recall *why*. Best-effort; never let it break deliberation.
    try:
        from services.memory.decision_memory import record_decision
        rejected = [a for a in approaches if a.get("key") != chosen_key]
        record_decision(
            goal, chosen_key, chosen_name=chosen_name, rationale=rationale,
            alternatives=rejected, context=context,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("decision_memory record skipped: %s", e)

    return {
        "chosen_key": chosen_key,
        "chosen_name": chosen_name,
        "rationale": rationale,
        "strategy_hint": strategy_hint,
        "approaches": approaches,
    }


def should_use_cognitive_workspace(goal: str, cfg: dict | None = None, plan_depth: int = 0) -> bool:
    """
    True when goal warrants multi-approach deliberation.
    Similar to should_plan but for tree-of-thought style reasoning.

    Respects config keys:
      - ``enable_cognitive_workspace`` (default True) — master switch
      - ``deliberation_enabled`` (default True) — alias / fine-grained switch
      - ``deliberation_min_length`` (default 100) — minimum goal length to trigger
    """
    if cfg is not None and not cfg.get("enable_cognitive_workspace", True):
        return False
    if cfg is not None and not cfg.get("deliberation_enabled", True):
        return False
    max_depth = int(cfg.get("max_plan_depth", 3)) if cfg else 3
    if plan_depth >= max_depth:
        return False
    g = (goal or "").strip()
    min_len = int(cfg.get("deliberation_min_length", 100)) if cfg else 100
    if len(g) < min_len:
        return False
    # Complex/problem-solving keywords
    keywords = (
        "analyze", "debug", "investigate", "figure out", "understand why",
        "refactor", "design", "architecture", "complex", "complicated",
    )
    return any(kw in g.lower() for kw in keywords)
