"""World state model (BL-241) — one live view of the environment Layla acts in.

Instead of each turn re-deriving context in isolation, this assembles a single snapshot
from the sources that already exist: the current project context, the known/open projects,
the repo-index stats, the machine's hardware, and the resource-governor mode. Every source
is read best-effort and independently, so a missing subsystem degrades that field to a
sane default rather than failing the whole snapshot. Decisions can consult *current* state.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        logger.debug("world_state source failed: %s", e)
        return default


def _hardware() -> dict[str, Any]:
    from install.hardware_probe import probe_hardware
    return probe_hardware()


def _current_project() -> dict[str, Any]:
    from layla.memory.projects_db import get_project_context
    return get_project_context()


def _projects() -> list[dict]:
    from layla.memory.projects_db import list_projects
    rows = list_projects(limit=50) or []
    return [{"name": p.get("name", ""), "workspace_root": p.get("workspace_root", "")} for p in rows]


def _repo_index() -> dict[str, int]:
    from services.workspace.repo_indexer import get_stats
    return get_stats()


def _governor() -> str:
    from services.infrastructure.resource_governor import get_mode
    return get_mode().value


def snapshot() -> dict[str, Any]:
    """A best-effort unified snapshot of the current world state."""
    project = _safe(_current_project, {})
    return {
        "current_project": {
            "name": project.get("project_name", ""),
            "lifecycle_stage": project.get("lifecycle_stage", ""),
            "goals": project.get("goals", ""),
            "progress": project.get("progress", ""),
            "blockers": project.get("blockers", ""),
            "domains": project.get("domains", []),
        },
        "projects": _safe(_projects, []),
        "repo_index": _safe(_repo_index, {"files": 0, "symbols": 0, "imports": 0, "calls": 0}),
        "hardware": _safe(_hardware, {}),
        "resource_mode": _safe(_governor, "unknown"),
    }


def summarize() -> str:
    """A compact one-paragraph digest of the snapshot for prompt injection."""
    s = snapshot()
    cp = s["current_project"]
    hw = s["hardware"]
    parts: list[str] = []
    if cp.get("name"):
        stage = f" [{cp['lifecycle_stage']}]" if cp.get("lifecycle_stage") else ""
        parts.append(f"Project: {cp['name']}{stage}.")
        if cp.get("blockers"):
            parts.append(f"Blockers: {cp['blockers']}.")
    if s["projects"]:
        parts.append(f"{len(s['projects'])} known project(s).")
    idx = s["repo_index"]
    if idx.get("files"):
        parts.append(f"Index: {idx['files']} files / {idx['symbols']} symbols.")
    if hw.get("ram_gb"):
        parts.append(f"Machine: {hw.get('cpu_logical', '?')} cores, {hw['ram_gb']}GB RAM"
                     + (f", GPU {hw['gpu_name']}" if hw.get("gpu_name") else "") + ".")
    parts.append(f"Mode: {s['resource_mode']}.")
    return " ".join(parts)
