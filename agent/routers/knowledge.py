"""Knowledge ingest and workspace indexing / cognition."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.route_helpers import sync_ingest_docs

logger = logging.getLogger("layla")
router = APIRouter(tags=["knowledge"])


@router.get("/knowledge/ingest/sources")
def knowledge_ingest_sources_list():
    try:
        from services.doc_ingestion import list_ingested_sources

        return {"sources": list_ingested_sources()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/knowledge/ingest")
async def knowledge_ingest_run(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        out = await asyncio.to_thread(
            sync_ingest_docs,
            str(body.get("source") or ""),
            str(body.get("label") or ""),
        )
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/workspace/index")
def workspace_index(req: dict):
    """Index workspace for semantic code search."""
    root = (req or {}).get("workspace_root", "")
    if not root:
        return JSONResponse({"ok": False, "error": "workspace_root required"})
    try:
        resolved = Path(root).expanduser().resolve()
        if not resolved.exists():
            return JSONResponse({"ok": False, "error": "workspace_root path does not exist"})
        if not resolved.is_dir():
            return JSONResponse({"ok": False, "error": "workspace_root must be a directory"})
        from services.workspace_index import index_workspace

        result = index_workspace(str(resolved))
        return {"ok": True, "indexed": result.get("indexed", 0), "skipped": result.get("skipped", 0), "errors": result.get("errors", [])}
    except Exception as e:
        logger.debug("workspace index failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/workspace/cognition/sync")
def workspace_cognition_sync(req: dict):
    body = req or {}
    roots = body.get("workspace_roots")
    if isinstance(roots, str):
        roots = [roots]
    if not isinstance(roots, list) or not roots:
        return JSONResponse({"ok": False, "error": "workspace_roots (non-empty list) required"}, status_code=400)
    index_semantic = bool(body.get("index_semantic", False))
    labels = body.get("labels") if isinstance(body.get("labels"), dict) else {}
    try:
        from services.repo_cognition import sync_repo_cognition

        out = sync_repo_cognition(
            [str(x) for x in roots if str(x).strip()],
            index_semantic=index_semantic,
            labels={str(k): str(v) for k, v in labels.items()},
        )
        return JSONResponse(out)
    except Exception as e:
        logger.warning("workspace cognition sync failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/workspace/cognition")
def workspace_cognition_list(limit: int = 50):
    try:
        from layla.memory.db import list_repo_cognition_snapshots

        return JSONResponse({"ok": True, "snapshots": list_repo_cognition_snapshots(limit=limit)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
