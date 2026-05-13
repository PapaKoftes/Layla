# -*- coding: utf-8 -*-
"""
long_horizon_planner.py — Multi-day task decomposition and checkpoint management.

Breaks large tasks (40+ hours) into day-sized chunks with dependency tracking,
resource estimation, and checkpoint saves for resume-after-shutdown.

Integrates with:
  - services/planner.py (create_plan for intra-day step generation)
  - services/plan_workspace_store.py (persistence)
  - layla/memory/missions_db.py (mission tracking)

Config keys:
    long_horizon_enabled          bool  (default true)
    max_horizon_days              int   (default 14)
    hours_per_day_chunk           float (default 4.0)
    checkpoint_auto_save          bool  (default true)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class DayChunk:
    """One day-sized work chunk within a long-horizon plan."""
    day: int                          # Day number (1-indexed)
    title: str                        # Short title for the chunk
    goal: str                         # What to accomplish
    estimated_hours: float = 4.0      # Estimated effort
    estimated_tokens: int = 0         # Estimated token spend
    depends_on: list[int] = field(default_factory=list)  # Day numbers this depends on
    status: str = "pending"           # pending | running | done | blocked
    artifacts: list[str] = field(default_factory=list)   # Expected output files/learnings
    checkpoint_id: str = ""           # Checkpoint ID for resume

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LongHorizonPlan:
    """Multi-day plan with dependency graph and resource estimation."""
    id: str
    goal: str
    chunks: list[DayChunk] = field(default_factory=list)
    total_estimated_hours: float = 0.0
    total_estimated_tokens: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"            # active | paused | completed | abandoned

    def to_dict(self) -> dict:
        d = asdict(self)
        d["chunks"] = [c.to_dict() for c in self.chunks]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> LongHorizonPlan:
        chunks = [DayChunk(**c) for c in d.get("chunks", [])]
        return cls(
            id=d["id"], goal=d["goal"], chunks=chunks,
            total_estimated_hours=d.get("total_estimated_hours", 0),
            total_estimated_tokens=d.get("total_estimated_tokens", 0),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            status=d.get("status", "active"),
        )


# ── Decomposition ───────────────────────────────────────────────────────────

def _estimate_complexity(goal: str) -> float:
    """Rough hour estimate based on goal text analysis."""
    words = len(goal.split())
    # Base: 2 hours for simple tasks, scaling up
    base = 2.0
    if words > 100:
        base += 4.0
    if words > 50:
        base += 2.0
    # Keyword multipliers
    lower = goal.lower()
    if any(kw in lower for kw in ("refactor", "redesign", "rewrite", "migrate")):
        base *= 1.5
    if any(kw in lower for kw in ("test", "coverage", "documentation")):
        base += 2.0
    if any(kw in lower for kw in ("full", "complete", "comprehensive", "entire")):
        base *= 1.3
    return round(base, 1)


def decompose_to_horizon(
    goal: str,
    *,
    cfg: dict | None = None,
    max_days: int | None = None,
    hours_per_day: float | None = None,
) -> LongHorizonPlan:
    """
    Decompose a large goal into day-sized chunks.

    First attempts LLM-based decomposition; falls back to heuristic splitting.
    """
    import hashlib
    cfg = cfg or {}

    if not cfg.get("long_horizon_enabled", True):
        # Return single-chunk plan
        plan_id = hashlib.sha256(goal.encode()).hexdigest()[:12]
        return LongHorizonPlan(
            id=plan_id, goal=goal,
            chunks=[DayChunk(day=1, title="Execute task", goal=goal)],
            total_estimated_hours=_estimate_complexity(goal),
        )

    max_d = max_days or int(cfg.get("max_horizon_days", 14))
    hpd = hours_per_day or float(cfg.get("hours_per_day_chunk", 4.0))
    plan_id = hashlib.sha256(f"{goal}:{time.time()}".encode()).hexdigest()[:12]

    # Try LLM decomposition
    chunks = _llm_decompose(goal, max_d, hpd, cfg)
    if not chunks:
        chunks = _heuristic_decompose(goal, max_d, hpd)

    total_hours = sum(c.estimated_hours for c in chunks)
    total_tokens = int(total_hours * 500_000)  # ~500K tokens per hour of work

    plan = LongHorizonPlan(
        id=plan_id, goal=goal, chunks=chunks,
        total_estimated_hours=total_hours,
        total_estimated_tokens=total_tokens,
    )
    return plan


def _llm_decompose(goal: str, max_days: int, hours_per_day: float, cfg: dict) -> list[DayChunk]:
    """Use LLM to decompose goal into day-chunks. Returns [] on failure."""
    try:
        from services.llm_gateway import run_completion
        prompt = (
            f"You are a project planner. Break this goal into {max_days} or fewer day-sized work chunks, "
            f"each approximately {hours_per_day} hours of effort.\n\n"
            f"Goal: {goal}\n\n"
            "Return a JSON array of objects with keys: day (int), title (str), goal (str), "
            "estimated_hours (float), depends_on (list of day numbers, or empty). "
            "Return ONLY the JSON array."
        )
        resp = run_completion(prompt, max_tokens=1000, temperature=0.3)
        text = resp if isinstance(resp, str) else (
            resp.get("choices", [{}])[0].get("message", {}).get("content", "") if isinstance(resp, dict) else ""
        )
        text = text.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

        raw = json.loads(text)
        if not isinstance(raw, list) or len(raw) < 1:
            return []

        chunks = []
        for i, item in enumerate(raw[:max_days]):
            chunks.append(DayChunk(
                day=item.get("day", i + 1),
                title=str(item.get("title", f"Day {i+1}"))[:100],
                goal=str(item.get("goal", ""))[:500],
                estimated_hours=min(hours_per_day * 2, max(0.5, float(item.get("estimated_hours", hours_per_day)))),
                depends_on=[int(d) for d in item.get("depends_on", []) if isinstance(d, (int, float))],
            ))
        return chunks
    except Exception as exc:
        logger.debug("long_horizon_planner: LLM decompose failed: %s", exc)
        return []


def _heuristic_decompose(goal: str, max_days: int, hours_per_day: float) -> list[DayChunk]:
    """Heuristic decomposition: split goal by phases."""
    total_hours = _estimate_complexity(goal)
    n_days = max(1, min(max_days, int(total_hours / hours_per_day) + 1))

    # Standard phase structure
    _phases = [
        ("Research & Planning", "Understand requirements, research approaches, create detailed plan"),
        ("Core Implementation", "Build the main functionality and data structures"),
        ("Integration & Wiring", "Connect components, wire into existing systems"),
        ("Testing & Validation", "Write tests, run health checks, fix issues"),
        ("Polish & Documentation", "Clean up code, add comments, update docs"),
    ]

    chunks = []
    for i in range(n_days):
        phase_idx = min(i, len(_phases) - 1)
        title, desc = _phases[phase_idx]
        if i >= len(_phases):
            title = f"Continuation (Day {i + 1})"
            desc = f"Continue implementation of: {goal[:100]}"

        chunks.append(DayChunk(
            day=i + 1,
            title=title,
            goal=f"{desc}\n\nOverall goal: {goal[:200]}",
            estimated_hours=min(hours_per_day, total_hours / n_days),
            depends_on=[i] if i > 0 else [],
        ))

    return chunks


# ── Checkpoint management ────────────────────────────────────────────────────

_CHECKPOINT_DIR = Path.home() / ".layla" / "checkpoints"


def save_checkpoint(plan: LongHorizonPlan) -> str:
    """Save plan state to disk for resume-after-shutdown. Returns checkpoint path."""
    _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = _CHECKPOINT_DIR / f"horizon_{plan.id}.json"
    plan.updated_at = time.time()
    path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    logger.info("long_horizon: checkpoint saved → %s", path)
    return str(path)


def load_checkpoint(plan_id: str) -> LongHorizonPlan | None:
    """Load plan from checkpoint."""
    path = _CHECKPOINT_DIR / f"horizon_{plan_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LongHorizonPlan.from_dict(data)
    except Exception as exc:
        logger.warning("long_horizon: failed to load checkpoint %s: %s", plan_id, exc)
        return None


def list_checkpoints() -> list[dict]:
    """List all saved horizon plan checkpoints."""
    if not _CHECKPOINT_DIR.is_dir():
        return []
    results = []
    for path in sorted(_CHECKPOINT_DIR.glob("horizon_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append({
                "id": data.get("id", ""),
                "goal": data.get("goal", "")[:100],
                "status": data.get("status", "unknown"),
                "chunks": len(data.get("chunks", [])),
                "total_hours": data.get("total_estimated_hours", 0),
                "updated_at": data.get("updated_at", 0),
            })
        except Exception:
            pass
    return results


def advance_chunk(plan: LongHorizonPlan, day: int) -> bool:
    """Mark a chunk as done and update plan status."""
    for chunk in plan.chunks:
        if chunk.day == day:
            chunk.status = "done"
            break
    else:
        return False

    # Unblock dependent chunks
    done_days = {c.day for c in plan.chunks if c.status == "done"}
    for chunk in plan.chunks:
        if chunk.status == "blocked":
            if all(d in done_days for d in chunk.depends_on):
                chunk.status = "pending"

    # Check if all chunks are done
    if all(c.status == "done" for c in plan.chunks):
        plan.status = "completed"

    plan.updated_at = time.time()
    return True


def get_next_chunk(plan: LongHorizonPlan) -> DayChunk | None:
    """Get the next runnable chunk (pending + dependencies met)."""
    done_days = {c.day for c in plan.chunks if c.status == "done"}
    for chunk in plan.chunks:
        if chunk.status == "pending":
            if all(d in done_days for d in chunk.depends_on):
                return chunk
    return None
