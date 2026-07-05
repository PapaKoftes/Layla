"""Cross-project reasoning (BL-232) — discover links + transferable knowledge across projects.

Builds a `networkx` graph over the projects Layla knows (from `layla_projects` + their
per-project memory): each project contributes a term set (modules, file names, plan goal, dirs,
todos, decisions); projects that share enough terms are linked, weighted by overlap. Surfaces,
for a given project, the most-related other projects and *what* they share — so a decision in one
repo can borrow context from a sibling. Prebuilt-OSS: `networkx` for the graph.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_STOP = {
    "the", "and", "for", "with", "this", "that", "from", "into", "then", "your", "you", "are",
    "was", "will", "have", "has", "not", "but", "can", "all", "any", "src", "lib", "app", "test",
    "tests", "main", "index", "init", "utils", "util", "com", "www", "http", "https", "json", "yaml",
    "readme", "license", "node_modules", "dist", "build", "temp", "tmp", "data", "config",
}
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")  # underscores separate (snake_case -> words)


def _tokens(*texts: Any) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for tok in _TOKEN.findall(str(t or "")):
            low = tok.lower()
            if low not in _STOP and len(low) >= 3:
                out.add(low)
    return out


def _project_terms(mem: dict) -> set[str]:
    """Distinctive terms for a project from its memory document."""
    terms: set[str] = set()
    terms |= _tokens(*(mem.get("modules") or {}).keys())
    terms |= _tokens(*[Path(f).stem for f in (mem.get("files") or {}).keys()])
    struct = mem.get("structure") or {}
    terms |= _tokens(*(struct.get("top_level_dirs") or []))
    terms |= _tokens(*(struct.get("entrypoint_hints") or []))
    plan = mem.get("plan") or {}
    terms |= _tokens(plan.get("goal"))
    terms |= _tokens(*[t if isinstance(t, str) else (t or {}).get("text", "") for t in (mem.get("todos") or [])])
    terms |= _tokens(*[d if isinstance(d, str) else (d or {}).get("text", "") for d in (mem.get("decisions") or [])])
    return terms


def _iter_projects() -> list[dict]:
    try:
        from layla.memory.projects_db import list_projects
        return list_projects(limit=200) or []
    except Exception:
        return []


def _load_terms_for(project: dict) -> tuple[str, set[str]]:
    root = str(project.get("workspace_root") or "").strip()
    name = str(project.get("name") or project.get("id") or root or "project")
    if not root:
        return name, set()
    try:
        from services.memory.project_memory import load_project_memory
        mem = load_project_memory(Path(root)) or {}
    except Exception:
        mem = {}
    return name, _project_terms(mem)


def build_project_graph(min_shared: int = 2):
    """Return a networkx.Graph of projects linked by shared terms (edge weight = overlap size)."""
    import networkx as nx

    g = nx.Graph()
    entries = []
    for p in _iter_projects():
        name, terms = _load_terms_for(p)
        g.add_node(name, terms=terms, workspace_root=str(p.get("workspace_root") or ""))
        entries.append((name, terms))
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            shared = entries[i][1] & entries[j][1]
            if len(shared) >= min_shared:
                g.add_edge(entries[i][0], entries[j][0], weight=len(shared), shared=sorted(shared)[:20])
    return g


def related_projects(name_or_root: str, *, limit: int = 5, min_shared: int = 2) -> dict[str, Any]:
    """For a project (by name or workspace_root), the most-related others + what they share."""
    import networkx as nx

    g = build_project_graph(min_shared=min_shared)
    target = None
    key = str(name_or_root or "").strip()
    for n, d in g.nodes(data=True):
        if n == key or d.get("workspace_root") == key:
            target = n
            break
    if target is None:
        return {"ok": False, "error": "project not found", "projects": [n for n in g.nodes]}
    neighbors = sorted(
        ((nb, g[target][nb]["weight"], g[target][nb].get("shared", [])) for nb in g.neighbors(target)),
        key=lambda x: -x[1],
    )[:limit]
    return {
        "ok": True,
        "project": target,
        "related": [{"project": nb, "shared_count": w, "shared_terms": sh} for nb, w, sh in neighbors],
    }


def project_clusters(min_shared: int = 3) -> dict[str, Any]:
    """Connected components = clusters of related projects (shared tooling/domain)."""
    import networkx as nx

    g = build_project_graph(min_shared=min_shared)
    clusters = [sorted(c) for c in nx.connected_components(g) if len(c) > 1]
    return {"ok": True, "clusters": clusters, "project_count": g.number_of_nodes()}
