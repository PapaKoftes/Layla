from __future__ import annotations

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

router = APIRouter(tags=["improvements"])


@router.get("/improvements")
def improvements_list(status: str = "", limit: int = 50):
    try:
        from services.self_improvement import list_proposals

        return JSONResponse(list_proposals(status=status or "", limit=limit))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/improvements/generate")
def improvements_generate(req: dict = Body(default={})):
    try:
        import runtime_safety
        from services.self_improvement import generate_proposals

        body = req if isinstance(req, dict) else {}
        out = generate_proposals(
            session_summary=(body.get("session_summary") or ""),
            capability_levels=body.get("capability_levels") if isinstance(body.get("capability_levels"), dict) else None,
            recent_failures=body.get("recent_failures") if isinstance(body.get("recent_failures"), list) else None,
        )
        try:
            cfg = runtime_safety.load_config()
            if cfg.get("initiative_project_proposals_enabled", False):
                from services.initiative_engine import generate_project_proposals

                ws = (body.get("workspace_root") or "").strip() or str(runtime_safety.REPO_ROOT)
                out["project_proposals"] = generate_project_proposals(ws, cfg)
        except Exception:
            pass
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/improvements/approve_batch")
def improvements_approve_batch(req: dict = Body(default={})):
    try:
        from services.self_improvement import approve_batch

        body = req if isinstance(req, dict) else {}
        ids = body.get("ids") if isinstance(body.get("ids"), list) else []
        return JSONResponse(approve_batch([int(x) for x in ids if str(x).isdigit()]))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/improvements/reject")
def improvements_reject(req: dict = Body(default={})):
    try:
        from services.self_improvement import reject

        body = req if isinstance(req, dict) else {}
        ids = body.get("ids") if isinstance(body.get("ids"), list) else []
        return JSONResponse(reject([int(x) for x in ids if str(x).isdigit()]))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

