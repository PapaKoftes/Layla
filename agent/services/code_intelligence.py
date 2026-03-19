"""
Code intelligence facade over workspace_index: symbol search, graph context, semantic workspace search.
Read-only; paths must stay within sandbox (caller validates).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


def search_symbols(
    workspace_root: str | Path,
    symbol: str,
    *,
    k: int = 20,
) -> dict[str, Any]:
    """
    Find functions/classes matching symbol (substring, case-insensitive).
    Uses workspace graph when built; falls back to scanning .py with tree-sitter.
    """
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        return {"ok": False, "error": "Invalid workspace root", "matches": []}
    sym = (symbol or "").strip()
    if len(sym) < 1:
        return {"ok": False, "error": "symbol required", "matches": []}
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from services.workspace_index import build_workspace_graph, search_workspace, _workspace_graph
    except Exception as e:
        logger.debug("code_intelligence import workspace_index: %s", e)
        return {"ok": False, "error": "workspace_index unavailable", "matches": []}

    try:
        if not _workspace_graph:
            build_workspace_graph(root)
    except Exception as e:
        logger.debug("build_workspace_graph: %s", e)

    sl = sym.lower()
    try:
        for nid, data in (_workspace_graph or {}).items():
            if data.get("type") not in ("function", "class"):
                continue
            label = (data.get("label") or "")
            if sl not in label.lower():
                continue
            fp = data.get("file") or ""
            key = f"{fp}::{label}"
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                {
                    "name": label,
                    "type": data.get("type"),
                    "file": fp,
                    "node_id": nid,
                }
            )
            if len(matches) >= k:
                break
    except Exception as e:
        logger.debug("graph symbol scan: %s", e)

    if len(matches) < k // 2:
        try:
            sem = search_workspace(sym, workspace_root=root, k=min(8, k))
            for row in sem:
                text = (row.get("text") or "")[:200]
                src = row.get("source") or ""
                key = f"sem::{src}"
                if key in seen:
                    continue
                seen.add(key)
                matches.append({"name": sym, "type": "semantic_chunk", "file": src, "excerpt": text})
                if len(matches) >= k:
                    break
        except Exception as e:
            logger.debug("semantic workspace search: %s", e)

    if not matches:
        try:
            from services.workspace_index import get_architecture_summary

            summary = get_architecture_summary(root)
            if summary and sl in summary.lower():
                matches.append(
                    {
                        "name": symbol,
                        "type": "architecture_summary",
                        "file": "",
                        "excerpt": summary[:1200],
                    }
                )
        except Exception:
            pass

    return {"ok": True, "symbol": sym, "matches": matches[:k], "count": len(matches[:k])}
