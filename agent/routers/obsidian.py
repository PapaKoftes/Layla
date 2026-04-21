"""Phase 5.1 — Obsidian Vault Connector router."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("layla")
router = APIRouter(tags=["obsidian"])

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@router.post("/obsidian/connect")
async def obsidian_connect(request: Request):
    """Set the Obsidian vault path. Persists to config."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    vault_path = str((body or {}).get("vault_path") or "").strip()
    if not vault_path:
        return JSONResponse({"ok": False, "error": "vault_path is required"}, status_code=400)
    try:
        from services.obsidian_sync import set_vault_path
        return set_vault_path(vault_path)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/obsidian/status")
def obsidian_status():
    """Return vault connection status and last-sync info."""
    try:
        from services.obsidian_sync import diff_vault, get_vault_path
        vp = get_vault_path()
        if vp is None:
            return {"connected": False, "vault_path": None}
        d = diff_vault(_REPO_ROOT)
        return {
            "connected": True,
            "vault_path": str(vp),
            "new": len(d.get("new", [])),
            "updated": len(d.get("updated", [])),
            "unchanged": len(d.get("unchanged", [])),
            "conflicts": len(d.get("conflicts", [])),
            "total_vault_files": d.get("total_vault_files", 0),
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/obsidian/diff")
def obsidian_diff():
    """Show what files would change on next sync (dry-run)."""
    try:
        from services.obsidian_sync import diff_vault
        return diff_vault(_REPO_ROOT)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/obsidian/sync")
async def obsidian_sync(request: Request):
    """Sync vault → knowledge/obsidian. Pass force=true to overwrite conflicts."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    force = bool((body or {}).get("force", False))
    try:
        from services.obsidian_sync import sync_vault
        return sync_vault(_REPO_ROOT, force=force)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/obsidian/suggest")
def obsidian_suggest(n: int = 10):
    """Suggest Layla learnings to export back to the vault as .md notes."""
    try:
        from services.obsidian_sync import suggest_export
        return suggest_export(n=max(1, min(50, n)))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/obsidian/export")
async def obsidian_export(request: Request):
    """Export approved learning IDs to vault/layla-exports/ directory."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    ids = list((body or {}).get("ids") or [])
    if not ids:
        return JSONResponse({"ok": False, "error": "ids list is required"}, status_code=400)
    try:
        from services.obsidian_sync import export_to_vault
        return export_to_vault([str(i) for i in ids], _REPO_ROOT)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
