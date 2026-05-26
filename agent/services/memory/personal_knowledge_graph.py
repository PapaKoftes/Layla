"""
Personal knowledge graph: unified graph linking timeline events, projects, goals, identity, knowledge.
Used during retrieval and reasoning.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

# In-memory graph: nodes {id: {type, label, ...}}, edges [(src, tgt, type)]
_pkg_nodes: dict[str, dict[str, Any]] = {}
_pkg_edges: list[tuple[str, str, str]] = []
_pkg_built = False


def _build_personal_graph() -> None:
    """Build unified graph from timeline, projects, goals, identity, learnings."""
    global _pkg_nodes, _pkg_edges, _pkg_built
    if _pkg_built:
        return
    _pkg_nodes = {}
    _pkg_edges = []
    try:
        from layla.memory.db import (
            get_active_goals,
            get_all_user_identity,
            get_project_context,
            get_recent_learnings,
            get_recent_timeline_events,
        )
        # Project node
        pc = get_project_context()
        pid = "project:current"
        if pc.get("project_name"):
            _pkg_nodes[pid] = {"type": "project", "label": pc["project_name"], "goals": pc.get("goals", "")[:200]}
        else:
            _pkg_nodes[pid] = {"type": "project", "label": "current", "goals": ""}
        # Goals
        for g in get_active_goals(pc.get("project_name", ""))[:5]:
            gid = f"goal:{g.get('id', '')}"
            _pkg_nodes[gid] = {"type": "goal", "label": g.get("title", "")[:100]}
            _pkg_edges.append((pid, gid, "has_goal"))
        # Identity
        uid = get_all_user_identity()
        if uid:
            nid = "identity:user"
            _pkg_nodes[nid] = {"type": "identity", "label": "user", "attrs": uid}
        # Timeline events (recent)
        for t in get_recent_timeline_events(n=10, min_importance=0.3):
            tid = f"timeline:{t.get('id')}"
            _pkg_nodes[tid] = {"type": "timeline", "label": (t.get("content") or "")[:80], "event_type": t.get("event_type")}
            _pkg_edges.append(("project:current", tid, "includes"))
        # Learnings (sample)
        for L in get_recent_learnings(n=15):
            lid = f"learning:{L.get('id')}"
            _pkg_nodes[lid] = {"type": "learning", "label": (L.get("content") or "")[:80], "kind": L.get("type", "fact")}
            _pkg_edges.append(("project:current", lid, "informed_by"))
        _pkg_built = True
    except Exception as e:
        logger.debug("personal knowledge graph build failed: %s", e)


def get_personal_graph_context(query: str, max_chars: int = 500) -> str:
    """
    Return context string from personal knowledge graph relevant to query.
    Used during retrieval and reasoning.
    """
    _build_personal_graph()
    if not _pkg_nodes:
        return ""
    q_lower = (query or "").lower().split()
    relevant: list[str] = []
    for nid, data in _pkg_nodes.items():
        label = (data.get("label") or "").lower()
        if any(w in label for w in q_lower if len(w) > 2):
            t = data.get("type", "")
            if t == "project":
                relevant.append(f"Project: {data.get('label')}")
            elif t == "goal":
                relevant.append(f"Goal: {data.get('label')}")
            elif t == "timeline":
                relevant.append(f"Timeline: {data.get('label')}...")
            elif t == "learning":
                relevant.append(f"Learning: {data.get('label')}...")
    if not relevant:
        # Fallback: include project and top goals
        for nid, data in _pkg_nodes.items():
            if data.get("type") == "project":
                relevant.append(f"Project: {data.get('label')}")
            elif data.get("type") == "goal" and len(relevant) < 3:
                relevant.append(f"Goal: {data.get('label')}")
    return "\n".join(relevant[:8])[:max_chars] if relevant else ""


def invalidate_personal_graph() -> None:
    """Call when data changes; next get will rebuild."""
    global _pkg_built
    _pkg_built = False
