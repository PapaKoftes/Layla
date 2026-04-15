"""Knowledge ingest and workspace indexing / cognition."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routers.paths import REPO_ROOT
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


@router.post("/knowledge/import_chat_preview")
async def knowledge_import_chat_preview(request: Request):
    """Parse chat export text and return markdown preview stats (no disk write)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    fmt = str((body or {}).get("format") or "whatsapp").strip().lower()
    text = str((body or {}).get("text") or "")
    title = str((body or {}).get("title") or "chat_import").strip()[:120]
    try:
        if fmt == "whatsapp":
            from services.data_importers import parse_whatsapp_txt, whatsapp_export_to_markdown

            rows = parse_whatsapp_txt(text)
            md = whatsapp_export_to_markdown(text, title=title)
            return JSONResponse({"ok": True, "format": fmt, "messages_parsed": len(rows), "markdown_chars": len(md)})
        return JSONResponse({"ok": False, "error": "unsupported_format"}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/knowledge/import_chat")
async def knowledge_import_chat(request: Request):
    """Write parsed chat export as Markdown under repo ``knowledge/imports/`` for RAG indexing."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    fmt = str((body or {}).get("format") or "whatsapp").strip().lower()
    text = str((body or {}).get("text") or "")
    title = str((body or {}).get("title") or "chat_import").strip()[:120]
    if len(text) > 8_000_000:
        return JSONResponse({"ok": False, "error": "payload_too_large"}, status_code=400)
    try:
        if fmt == "whatsapp":
            from services.data_importers import whatsapp_export_to_markdown

            md = whatsapp_export_to_markdown(text, title=title)
        else:
            return JSONResponse({"ok": False, "error": "unsupported_format"}, status_code=400)
        safe = "".join(c for c in title if c.isalnum() or c in ("-", "_")).strip()[:64] or "import"
        dest_dir = REPO_ROOT / "knowledge" / "imports"
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{safe}.md"
        path.write_text(md, encoding="utf-8")
        return JSONResponse(
            {
                "ok": True,
                "path": str(path.relative_to(REPO_ROOT)),
                "markdown_chars": len(md),
            }
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
