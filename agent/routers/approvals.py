"""Pending approvals, approve, refresh lens knowledge."""
import threading

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from shared_state import get_audit, get_read_pending, get_write_pending_list

router = APIRouter(tags=["approvals"])

_approve_lock = threading.Lock()


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

    with _approve_lock:
        pending = read_pending()
        entry = next((e for e in pending if e.get("id") == approval_id), None)
        if not entry:
            return JSONResponse({"ok": False, "error": "Approval ID not found"})
        if entry.get("status") == "executed":
            # Idempotent: approving again should not re-run the tool.
            return JSONResponse({"ok": True, "result": entry.get("result", {}), "idempotent": True})
        # Expiry check — entries created with expires_at are rejected after TTL
        expires_at = entry.get("expires_at")
        if expires_at:
            try:
                from datetime import datetime, timezone
                from layla.time_utils import utcnow
                exp = datetime.fromisoformat(expires_at)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if utcnow() > exp:
                    entry["status"] = "expired"
                    write_pending_list(pending)
                    return JSONResponse(
                        {"ok": False, "error": "Approval request has expired", "expired": True},
                        status_code=410,
                    )
            except Exception:
                pass
        if entry.get("status") != "pending":
            return JSONResponse({"ok": False, "error": f"Entry status is already: {entry.get('status')}"})

        entry["status"] = "approved"
        from layla.time_utils import utcnow
        entry["approved_at"] = utcnow().isoformat()
        write_pending_list(pending)

        tool_name = entry.get("tool", "")
        args = entry.get("args", {})
        grant_pattern = (req or {}).get("grant_pattern", "").strip()
        save_for_session = bool((req or {}).get("save_for_session", False))
        if grant_pattern and tool_name:
            try:
                from layla.memory.db import add_tool_permission_grant
                add_tool_permission_grant(tool_name, grant_pattern, scope="permanent")
            except Exception:
                pass
        # D6: save_for_session — register an in-memory grant valid until process restart
        if save_for_session and tool_name:
            try:
                from services.session_grants import add_session_grant
                grant_scope = "command" if args.get("command") else "tool"
                grant_args = {}
                if grant_scope == "command":
                    cmd_parts = args.get("command", "").split()
                    # Use first two tokens as a glob pattern (e.g. "git status*")
                    grant_args["command"] = " ".join(cmd_parts[:2]) + "*" if len(cmd_parts) > 1 else args.get("command", "*")
                add_session_grant(tool_name, scope=grant_scope, args=grant_args)
            except Exception:
                pass
        result_ok = False
        tool_result = {}
        try:
            from layla.tools.registry import TOOLS
            if tool_name not in TOOLS:
                tool_result = {"ok": False, "error": f"Unknown tool: {tool_name}"}
            else:
                # Approval UI may attach preview-only keys (e.g. unified diff) — never pass those to tools.
                _skip = frozenset({"goal", "diff"})
                tool_result = TOOLS[tool_name]["fn"](**{k: v for k, v in args.items() if k not in _skip})
                result_ok = bool((tool_result or {}).get("ok", False))
        except Exception as e:
            tool_result = {"ok": False, "error": str(e)}

        entry["status"] = "executed"
        entry["result"] = tool_result
        write_pending_list(pending)
        audit(tool_name, str(args)[:80], "user", result_ok)

    return JSONResponse({"ok": True, "result": tool_result})


@router.post("/deny")
def deny_approval(req: dict):
    """Explicitly reject a pending approval — marks it denied so the agent knows."""
    approval_id = (req or {}).get("id", "").strip()
    if not approval_id:
        return JSONResponse({"ok": False, "error": "No id provided"})
    read_pending = get_read_pending()
    write_pending_list = get_write_pending_list()
    with _approve_lock:
        pending = read_pending()
        entry = next((e for e in pending if e.get("id") == approval_id), None)
        if not entry:
            return JSONResponse({"ok": False, "error": "Approval ID not found"})
        if entry.get("status") != "pending":
            return JSONResponse({"ok": False, "error": f"Already: {entry.get('status')}"})
        entry["status"] = "denied"
        from layla.time_utils import utcnow
        entry["denied_at"] = utcnow().isoformat()
        write_pending_list(pending)
    return JSONResponse({"ok": True})


@router.get("/session/grants")
def get_session_grants():
    """Return all active in-memory session grants."""
    try:
        from services.session_grants import list_session_grants
        return JSONResponse({"ok": True, "grants": list_session_grants()})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/session/grants/clear")
def clear_session_grants_route():
    """Revoke all session grants immediately."""
    try:
        from services.session_grants import clear_session_grants
        clear_session_grants()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


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
