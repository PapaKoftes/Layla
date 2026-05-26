"""Tiered character budgets for system-head sections (Phase 5 — North Star context caps).

Used with ``system_head_budget_ratio`` in runtime config. Call :func:`budgets_for_mode`
from prompt assembly when building section budgets.
"""
from __future__ import annotations

from typing import Any

# Per-section character budgets by reasoning depth (before n_ctx scaling).
BUDGET_MAP: dict[str, dict[str, int]] = {
    "none": {
        "identity": 200,
        "personality": 300,
        "memory": 0,
        "knowledge": 0,
        "workspace": 0,
        "policy": 200,
    },
    "light": {
        "identity": 200,
        "personality": 400,
        "memory": 600,
        "knowledge": 400,
        "workspace": 400,
        "policy": 300,
    },
    "deep": {
        "identity": 200,
        "personality": 500,
        "memory": 1200,
        "knowledge": 1000,
        "workspace": 800,
        "policy": 400,
    },
}


def tier_for_reasoning_mode(reasoning_mode: str | None, research_mode: bool = False) -> str:
    rm = (reasoning_mode or "").strip().lower()
    if research_mode or rm in ("deep", "deliberate", "heavy"):
        return "deep"
    if rm in ("none", "off", "minimal"):
        return "none"
    return "light"


def budgets_for_mode(reasoning_mode: str | None, research_mode: bool = False) -> dict[str, int]:
    """Return a copy of the tier budget map for the given mode."""
    tier = tier_for_reasoning_mode(reasoning_mode, research_mode)
    return dict(BUDGET_MAP.get(tier, BUDGET_MAP["light"]))


def merge_with_n_ctx(base: dict[str, int], n_ctx: int, head_ratio: float) -> dict[str, int]:
    """Scale section budgets so their sum fits roughly in n_ctx * head_ratio (chars ~ tokens*4 heuristic)."""
    cap_chars = max(2000, int(n_ctx * max(0.1, min(0.55, head_ratio)) * 3))
    total = sum(max(0, v) for v in base.values()) or 1
    scale = min(1.0, cap_chars / total)
    return {k: max(0, int(v * scale)) for k, v in base.items()}


def dedup_blocks(blocks: list[tuple[str, str]], max_keep: int = 64) -> list[tuple[str, str]]:
    """Drop exact-duplicate (title, body) pairs; keep order, cap size."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for title, body in blocks:
        key = (title.strip(), body.strip())
        if key in seen or not body.strip():
            continue
        seen.add(key)
        out.append((title, body))
        if len(out) >= max_keep:
            break
    return out
