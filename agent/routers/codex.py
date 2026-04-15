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


@router.get("/proposals")
def list_codex_proposals(workspace_root: str = Query("", description="Sandboxed workspace directory")):
    p, err = _resolve_workspace(workspace_root)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        from services.relationship_codex import list_proposals

        return JSONResponse(list_proposals(p))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/proposals/generate")
def generate_codex_proposals(
    workspace_root: str = Query("", description="Sandboxed workspace directory"),
    body: dict[str, Any] = Body(default={}),
):
    p, err = _resolve_workspace(workspace_root)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        from services.relationship_codex import generate_proposals

        goal_or_context = (body.get("goal_or_context") or "").strip() if isinstance(body, dict) else ""
        recent_actions = (body.get("recent_actions") or "").strip() if isinstance(body, dict) else ""
        return JSONResponse(generate_proposals(p, goal_or_context=goal_or_context, recent_actions=recent_actions))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/proposals/approve")
def approve_codex_proposal(
    workspace_root: str = Query("", description="Sandboxed workspace directory"),
    proposal_id: str = Query("", description="Proposal id"),
):
    p, err = _resolve_workspace(workspace_root)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        from services.relationship_codex import approve_proposal

        res = approve_proposal(p, proposal_id)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/proposals/dismiss")
def dismiss_codex_proposal(
    workspace_root: str = Query("", description="Sandboxed workspace directory"),
    proposal_id: str = Query("", description="Proposal id"),
):
    p, err = _resolve_workspace(workspace_root)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        from services.relationship_codex import dismiss_proposal

        res = dismiss_proposal(p, proposal_id)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
