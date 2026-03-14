"""Pending approvals, approve, refresh lens knowledge."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from shared_state import get_audit, get_read_pending, get_write_pending_list

router = APIRouter(tags=["approvals"])


@router.get("/pending")
def get_pending():
    return JSONResponse({"pending": get_read_pending()()})


@router.post("/approve")
def approve(req: dict):
    approval_id = (req or {}).get("id", "").strip()
    if not approval_id:
        return JSONResponse({"ok": False, "error": "No id provided"})

    read_pending = get_read_pending()
    write_pending_list = get_write_pending_list()
    audit = get_audit()

    pending = read_pending()
    entry = next((e for e in pending if e.get("id") == approval_id), None)
    if not entry:
        return JSONResponse({"ok": False, "error": "Approval ID not found"})
    if entry.get("status") != "pending":
        return JSONResponse({"ok": False, "error": f"Entry status is already: {entry.get('status')}"})

    entry["status"] = "approved"
    from layla.time_utils import utcnow
    entry["approved_at"] = utcnow().isoformat()
    write_pending_list(pending)

    tool_name = entry.get("tool", "")
    args = entry.get("args", {})
    result_ok = False
    tool_result = {}
    try:
        from layla.tools.registry import TOOLS
        if tool_name in TOOLS:
            tool_result = TOOLS[tool_name]["fn"](**{k: v for k, v in args.items() if k != "goal"})
            result_ok = bool(tool_result.get("ok", False))
    except Exception as e:
        tool_result = {"ok": False, "error": str(e)}

    entry["status"] = "executed"
    entry["result"] = tool_result
    write_pending_list(pending)
    audit(tool_name, str(args)[:80], "user", result_ok)

    return JSONResponse({"ok": True, "result": tool_result})


@router.post("/refresh_lens_knowledge")
def refresh_lens_knowledge():
    try:
        from lens_refresh import rebuild_lens_knowledge
        rebuild_lens_knowledge()
    except Exception as e:
        import logging
        logging.getLogger("layla").exception("refresh_lens_knowledge failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    return {"ok": True}
