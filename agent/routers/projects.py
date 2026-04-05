"""Layla projects API — scoped workspace / aspect / skills presets."""
from __future__ import annotations

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

router = APIRouter(tags=["projects"])


@router.get("/projects")
def list_projects(limit: int = 100):
    try:
        from layla.memory.db import list_projects as _list

        return JSONResponse({"ok": True, "projects": _list(limit=limit)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/projects")
def create_project(req: dict = Body(default={})):
    try:
        from layla.memory.db import create_project as _create

        body = req if isinstance(req, dict) else {}
        row = _create(
            name=str(body.get("name") or "New project"),
            workspace_root=str(body.get("workspace_root") or ""),
            aspect_default=str(body.get("aspect_default") or ""),
            skill_paths_json=str(body.get("skill_paths_json") or "[]"),
            system_preamble=str(body.get("system_preamble") or ""),
            project_id=str(body.get("id") or "").strip(),
            cognition_extra_roots=body.get("cognition_extra_roots"),
        )
        return JSONResponse({"ok": True, "project": row})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    try:
        from layla.memory.db import get_project as _get

        row = _get(project_id)
        if not row:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
        return JSONResponse({"ok": True, "project": row})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, req: dict = Body(default={})):
    try:
        from layla.memory.db import update_project as _upd

        body = req if isinstance(req, dict) else {}
        row = _upd(project_id, body)
        if not row:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
        return JSONResponse({"ok": True, "project": row})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.delete("/projects/{project_id}")
def remove_project(project_id: str):
    try:
        from layla.memory.db import delete_project as _del

        ok = _del(project_id)
        if not ok:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
