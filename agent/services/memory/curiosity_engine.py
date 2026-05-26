"""
Curiosity engine: identify knowledge gaps or missing documentation.
Generate suggestions for learning or exploration.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def identify_knowledge_gaps(workspace_root: str = "", project_context: dict | None = None) -> list[dict[str, Any]]:
    """
    Identify potential knowledge gaps: undocumented areas, missing docs, unexplored topics.
    Returns list of {suggestion, reason, priority}.
    """
    gaps: list[dict[str, Any]] = []
    try:
        from pathlib import Path

        from layla.memory.db import get_project_context, get_recent_learnings

        learnings = get_recent_learnings(n=30)
        learned_topics = set()
        for L in learnings:
            c = (L.get("content") or "").lower()
            for w in c.split():
                if len(w) > 4:
                    learned_topics.add(w)

        pc = project_context or get_project_context()
        proj = (pc.get("project_name") or "").lower()
        domains = pc.get("domains") or []
        goals = (pc.get("goals") or "").lower()

        # Gap: project has goals but no recent learnings about them
        if goals and len(learnings) < 5:
            gaps.append({
                "suggestion": f"Study or document: {goals[:80]}...",
                "reason": "Project has goals but few related learnings",
                "priority": 0.8,
            })

        # Gap: domains not in learnings
        for d in domains[:5]:
            if isinstance(d, str) and d.lower() not in learned_topics and d.lower() not in " ".join(learned_topics):
                gaps.append({
                    "suggestion": f"Explore or document domain: {d}",
                    "reason": f"Domain '{d}' has no recent learnings",
                    "priority": 0.6,
                })

        # Gap: workspace has Python but no architecture summary
        if workspace_root:
            root = Path(workspace_root).expanduser().resolve()
            if root.exists():
                py_count = sum(1 for _ in root.rglob("*.py") if ".git" not in str(_) and "__pycache__" not in str(_))
                if py_count > 5:
                    try:
                        from services.workspace_index import get_architecture_summary
                        arch = get_architecture_summary(root)
                        if not arch or len(arch.strip()) < 100:
                            gaps.append({
                                "suggestion": "Run workspace_map or index workspace to build code intelligence",
                                "reason": "Codebase has Python files but no architecture index",
                                "priority": 0.7,
                            })
                    except Exception:
                        pass

        # Gap: no study plans
        try:
            from layla.memory.db import get_active_study_plans
            plans = get_active_study_plans()
            if not plans and (proj or domains):
                gaps.append({
                    "suggestion": "Add study plans for project domains or goals",
                    "reason": "No active study plans",
                    "priority": 0.5,
                })
        except Exception:
            pass

        gaps.sort(key=lambda x: -x.get("priority", 0))
        return gaps[:10]
    except Exception as e:
        logger.debug("curiosity engine failed: %s", e)
        return []


def get_curiosity_suggestions(workspace_root: str = "") -> list[str]:
    """
    Return human-readable suggestions for learning or exploration.
    Used by wakeup, study router, or UI.
    """
    gaps = identify_knowledge_gaps(workspace_root=workspace_root)
    return [g.get("suggestion", "") for g in gaps if g.get("suggestion")][:5]
