"""
Token budgeting for prompt sections.
Allocates limits per section to prevent context overflow.
Integrates with context_manager.build_system_prompt().
Uses services/token_count.py (tiktoken) for accurate counting.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")

# Default token budgets per section (tunable via config prompt_budgets)
DEFAULT_BUDGETS: dict[str, int] = {
    "identity": 400,
    "pinned_context": 400,
    "memory": 800,
    "knowledge": 800,
    "graph_context": 200,
    "workspace_context": 400,
    # Legacy keys used by context_manager
    "system_instructions": 800,
    "agent_state": 400,
    "current_goal": 100,
    "knowledge_graph": 200,
    "tools": 0,
    "conversation": 800,
    "current_task": 200,
}


# Default share of the *context window* for ratio mode (sum = 1.0)
DEFAULT_CONTEXT_RATIOS: dict[str, float] = {
    "task": 0.20,
    "memory": 0.25,
    "code": 0.35,
    "tools": 0.10,
    "identity": 0.10,
}


def get_ratio_budgets(
    n_ctx: int = 4096,
    cfg: dict | None = None,
    reserve_for_response: int = 512,
) -> dict[str, int]:
    """
    Map high-level buckets (task, memory, code, tools, identity) onto context_manager section keys.

    Activated when tiered_prompt_budget_enabled and context_budget_ratio_mode are true.
    """
    if cfg is None:
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    available = max(512, int(n_ctx) - max(128, int(reserve_for_response)))
    ratios = dict(DEFAULT_CONTEXT_RATIOS)
    overrides = cfg.get("context_budget_ratios") if isinstance(cfg.get("context_budget_ratios"), dict) else {}
    for k, v in overrides.items():
        if k in ratios and v is not None:
            try:
                ratios[k] = float(v)
            except (TypeError, ValueError):
                pass
    s = sum(max(0.0, float(ratios[k])) for k in ratios)
    if s <= 0:
        s = 1.0
    # Map into existing section keys used by build_system_prompt
    task_tokens = int(available * float(ratios.get("task", 0.2)) / s)
    mem_tokens = int(available * float(ratios.get("memory", 0.25)) / s)
    code_tokens = int(available * float(ratios.get("code", 0.35)) / s)
    tool_tokens = int(available * float(ratios.get("tools", 0.10)) / s)
    ident_tokens = int(available * float(ratios.get("identity", 0.10)) / s)

    return {
        "current_task": max(80, task_tokens // 2),
        "current_goal": max(60, task_tokens // 2),
        "memory": max(100, mem_tokens // 2),
        "knowledge": max(100, mem_tokens - max(100, mem_tokens // 2)),
        "workspace_context": max(120, code_tokens),
        "tools": max(0, tool_tokens),
        "system_instructions": max(120, ident_tokens // 2),
        "pinned_context": max(80, ident_tokens // 2),
        "identity": max(80, ident_tokens),
        # Legacy aliases
        "system_instructions_shadow": max(80, ident_tokens // 3),
        "agent_state": max(80, task_tokens // 4),
        "conversation": max(100, int(available * 0.15)),
        "knowledge_graph": max(60, mem_tokens // 6),
    }


def get_budgets(n_ctx: int = 4096, cfg: dict | None = None) -> dict[str, int]:
    """
    Return token budgets for each prompt section, scaled to n_ctx.

    When n_ctx is provided (from the loaded model), budgets are computed
    proportionally so the system prompt never exceeds 75% of the context window.
    Operator overrides via config prompt_budgets are applied on top.
    """
    if cfg is None:
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}

    if cfg.get("context_budget_ratio_mode") and cfg.get("tiered_prompt_budget_enabled", True):
        return get_ratio_budgets(n_ctx, cfg)

    # Scale DEFAULT_BUDGETS proportionally to n_ctx.
    # Default total is ~4900 tokens (sum of DEFAULT_BUDGETS).
    _default_total = sum(v for v in DEFAULT_BUDGETS.values() if v > 0)
    _context_use_ratio = 0.75
    available = max(512, int(n_ctx * _context_use_ratio))
    scale = min(1.0, available / max(_default_total, 1))

    budgets: dict[str, int] = {}
    for k, v in DEFAULT_BUDGETS.items():
        if v <= 0:
            budgets[k] = 0
        else:
            budgets[k] = max(50, int(v * scale))

    # Operator overrides from config always win
    overrides = cfg.get("prompt_budgets") or {}
    for k, v in overrides.items():
        if k in budgets and v is not None:
            budgets[k] = max(0, int(v))
    return budgets


def build_budget_telemetry(n_ctx: int = 4096, last_metrics: dict | None = None) -> dict:
    """
    Build a human-readable context budget snapshot for telemetry / the /health/context_budget endpoint.

    Returns per-section {used, budget, pct} dicts, a warnings list, and run metadata.
    """
    budgets = get_budgets(n_ctx)
    section_tokens: dict[str, int] = (last_metrics or {}).get("section_tokens") or {}
    total_budget = max(512, int(n_ctx * 0.75))

    sections: dict[str, dict] = {}
    warnings: list[str] = []

    for key, budget in sorted(budgets.items()):
        used = int(section_tokens.get(key, 0))
        pct = round(used / budget * 100) if budget > 0 else 0
        entry: dict = {"used": used, "budget": budget, "pct": pct}
        if key == "tools":
            entry["note"] = "injected separately by orchestrator"
        sections[key] = entry
        if budget > 0 and pct >= 100:
            warnings.append(f"{key} at capacity ({used}/{budget} tokens)")
        elif budget > 0 and used > 0 and pct >= 85:
            warnings.append(f"{key} near capacity ({pct}%)")

    total_used = int((last_metrics or {}).get("total_tokens") or sum(section_tokens.values()))
    total_pct = round(total_used / total_budget * 100) if total_budget > 0 else 0
    sections["total"] = {"used": total_used, "budget": total_budget, "pct": total_pct}

    dropped: list[str] = list((last_metrics or {}).get("dropped_sections") or [])
    truncated: list[str] = list((last_metrics or {}).get("truncated_sections") or [])
    if dropped:
        warnings.append(f"Dropped sections (budget exhausted): {', '.join(dropped)}")
    if total_pct >= 90:
        warnings.append(f"Total context at {total_pct}% — consider reducing pinned context or memory k")

    return {
        "n_ctx": n_ctx,
        "sections": sections,
        "warnings": warnings,
        "dropped_sections": dropped,
        "truncated_sections": truncated,
        "dedup_removed": int((last_metrics or {}).get("dedup_removed") or 0),
    }


def rebalance_budget(
    budgets: dict[str, int],
    section_tokens: dict[str, int] | None = None,
    *,
    pressure_threshold: float = 0.85,
    cfg: dict | None = None,
) -> dict[str, int]:
    """
    Dynamic context budget reallocation (Phase 5).

    When context pressure exceeds *pressure_threshold*, shrink compressible
    sections (memory, knowledge, knowledge_graph, workspace_context) to make
    room for high-priority sections (system_instructions, current_goal,
    conversation).

    When pressure is low (<0.6), slightly expand memory/knowledge to use
    available headroom.

    Returns a new budgets dict (original is not mutated).
    """
    cfg = cfg or {}
    if not cfg.get("dynamic_budget_enabled", True):
        return dict(budgets)

    threshold = float(cfg.get("budget_pressure_threshold", pressure_threshold))
    used = section_tokens or {}
    total_budget = sum(v for v in budgets.values() if v > 0)
    total_used = sum(used.get(k, 0) for k in budgets)
    if total_budget <= 0:
        return dict(budgets)
    pressure = total_used / total_budget

    new = dict(budgets)

    # Compressible sections (ordered by compression priority)
    _compressible = ["knowledge_graph", "knowledge", "memory", "workspace_context", "pinned_context"]
    # Protected sections (never shrink)
    _protected = {"system_instructions", "current_goal", "conversation", "current_task", "tools"}

    if pressure > threshold:
        # High pressure: shrink compressible sections
        _shrink_factors = {
            "knowledge_graph": 0.4,
            "knowledge": 0.5,
            "memory": 0.6,
            "workspace_context": 0.7,
            "pinned_context": 0.6,
            "agent_state": 0.5,
        }
        for key in _compressible:
            if key in new and key not in _protected:
                factor = _shrink_factors.get(key, 0.7)
                new[key] = max(50, int(new[key] * factor))
        if "agent_state" in new:
            new["agent_state"] = max(50, int(new["agent_state"] * 0.5))
        logger.debug(
            "rebalance_budget: pressure %.2f > %.2f — shrunk compressible sections",
            pressure, threshold,
        )
    elif pressure < 0.6 and total_used > 0:
        # Low pressure: expand memory/knowledge to use headroom
        headroom = total_budget - total_used
        if headroom > 200:
            bonus = int(headroom * 0.3)
            for key in ("memory", "knowledge"):
                if key in new:
                    new[key] = new[key] + bonus // 2

    return new


def truncate_section(text: str, max_tokens: int, section_name: str = "") -> str:
    """
    Truncate text to fit within max_tokens.
    Preserves word boundaries when possible.
    Uses token_count for accuracy.
    """
    if not text or max_tokens <= 0:
        return ""
    try:
        from services.token_count import count_tokens
        est = count_tokens(text)
    except Exception:
        est = max(1, len(text) // 4)
    if est <= max_tokens:
        return text
    suffix = "..."
    target_chars = int(len(text) * max_tokens / max(est, 1))
    truncated = text[: max(1, target_chars - len(suffix))]
    last_space = truncated.rfind(" ")
    if last_space > target_chars // 2:
        truncated = truncated[: last_space]
    return (truncated or text[:50]).strip() + suffix
