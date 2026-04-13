"""HTTP API for workspace relationship codex (`.layla/relationship_codex.json`)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/codex", tags=["codex"])


def _resolve_workspace(workspace_root: str) -> tuple[Path | None, str | None]:
    raw = (workspace_root or "").strip()
    if not raw:
        return None, "workspace_root required"
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        return None, "workspace_root is not a directory"
    try:
        from layla.tools.registry import inside_sandbox

        if not inside_sandbox(p):
            return None, "workspace_root outside sandbox"
    except Exception as e:
        return None, str(e)
    return p, None


@router.get("/relationship")
def get_relationship_codex(workspace_root: str = Query("", description="Sandboxed workspace directory")):
    """Load relationship codex JSON for the workspace."""
    p, err = _resolve_workspace(workspace_root)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        from services.relationship_codex import load_codex

        data = load_codex(p)
        return JSONResponse({"ok": True, "path": str(p / ".layla" / "relationship_codex.json"), "data": data})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.put("/relationship")
def put_relationship_codex(
    workspace_root: str = Query("", description="Sandboxed workspace directory"),
    body: dict[str, Any] = Body(default={}),
):
    """Replace relationship codex JSON (must include entities dict)."""
    p, err = _resolve_workspace(workspace_root)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "body must be a JSON object"}, status_code=400)
    data = dict(body)
    if "entities" not in data:
        data["entities"] = {}
    if not isinstance(data["entities"], dict):
        return JSONResponse({"ok": False, "error": "entities must be an object"}, status_code=400)
    try:
        from services.relationship_codex import save_codex

        ok, msg = save_codex(p, data)
        if not ok:
            return JSONResponse({"ok": False, "error": msg or "save_failed"}, status_code=400)
        return JSONResponse({"ok": True, "path": str(p / ".layla" / "relationship_codex.json")})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
