"""
Inject deterministic workspace discovery brief when project memory is sparse (North Star §18 integration).
Uses discover_project (filesystem) — not run_project_discovery LLM unless operator calls it separately.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


def workspace_memory_is_sparse(workspace_root: Path) -> bool:
    """True when .layla/project_memory.json missing or has little structural content."""
    try:
        from services.project_memory import load_project_memory, memory_file_path

        root = workspace_root.resolve()
        p = memory_file_path(root)
        if not p.is_file():
            return True
        data = load_project_memory(root)
        if not data:
            return True
        mods = data.get("modules")
        files = data.get("files")
        sk = data.get("semantic_sketch") if isinstance(data.get("semantic_sketch"), dict) else {}
        sample = int(sk.get("file_sample_count") or 0)
        if isinstance(mods, dict) and len(mods) == 0 and isinstance(files, dict) and len(files) == 0:
            return True
        if sample == 0 and isinstance(files, dict) and len(files) == 0:
            return True
        return False
    except Exception as e:
        logger.debug("workspace_memory_is_sparse failed: %s", e)
        return False


def build_workspace_discovery_brief(workspace_root: str, cfg: dict[str, Any]) -> str:
    if not bool(cfg.get("project_discovery_auto_inject", False)):
        return ""
    wr = (workspace_root or "").strip()
    if not wr:
        return ""
    try:
        root = Path(wr).expanduser().resolve()
    except Exception:
        return ""
    if not workspace_memory_is_sparse(root):
        return ""
    try:
        from layla.tools.registry import inside_sandbox
        from services.project_discovery import discover_project

        if not inside_sandbox(root):
            return ""
        disc = discover_project(str(root))
        if not isinstance(disc, dict) or not disc.get("ok"):
            return ""
        exts = disc.get("extensions") or {}
        top_ext = list(exts.items())[:5]
        ext_line = ", ".join(f"{a}:{b}" for a, b in top_ext) if top_ext else "(none)"
        readme = (disc.get("readme_preview") or "").strip()
        readme_one = (readme.split("\n")[0][:120] + "…") if len(readme) > 120 else readme[:120]
        nfiles = disc.get("file_count", 0)
        lines = [
            "[Workspace scan — project memory sparse; deterministic discovery]",
            f"- Files sampled: {nfiles}",
            f"- Top extensions: {ext_line}",
        ]
        if readme_one:
            lines.append(f"- README line: {readme_one}")
        lines.append("- Consider scan_repo / update_project_memory or project_discovery tool for a fuller picture.")
        return "\n".join(lines) + "\n"
    except Exception as e:
        logger.debug("build_workspace_discovery_brief failed: %s", e)
        return ""
