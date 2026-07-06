"""Event-driven automation router (BL-233)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/automation", tags=["automation"])


def _require_local(request: Request) -> JSONResponse | None:
    """Defense-in-depth (security review Finding 1): creating/firing rules can run tools
    (run_macro/reindex) — keep it local-only regardless of the endpoint allowlist."""
    try:
        from services.safety.auth import is_direct_local
        host = request.client.host if request.client else None
        if not is_direct_local(request.headers, host):
            return JSONResponse({"ok": False, "error": "local-only endpoint"}, status_code=403)
    except Exception:
        return JSONResponse({"ok": False, "error": "trust check failed"}, status_code=403)
    return None


class RuleBody(BaseModel):
    name: str
    event: str
    action: str
    match_glob: str = ""
    params: dict[str, Any] = {}
    enabled: bool = True


class EmitBody(BaseModel):
    event: str
    payload: dict[str, Any] = {}


@router.get("/rules")
def list_rules():
    from services.automation.rules_engine import EVENT_TYPES, ACTION_TYPES, list_rules
    return {"rules": list_rules(), "event_types": list(EVENT_TYPES), "action_types": list(ACTION_TYPES)}


@router.post("/rules")
def add_rule(body: RuleBody, request: Request):
    _b = _require_local(request)
    if _b is not None:
        return _b
    from services.automation.rules_engine import add_rule as _add
    return _add(
        body.name, body.event, body.action,
        match_glob=body.match_glob, params=body.params, enabled=body.enabled,
    )


@router.post("/rules/{rule_id}/enabled")
def set_enabled(rule_id: int, enabled: bool = True):
    from services.automation.rules_engine import set_enabled as _set
    return _set(rule_id, enabled)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int):
    from services.automation.rules_engine import delete_rule as _del
    return _del(rule_id)


@router.post("/emit")
def emit(body: EmitBody, request: Request):
    """Manually fire an event (for git hooks, schedulers, or testing)."""
    _b = _require_local(request)
    if _b is not None:
        return _b
    from services.automation.rules_engine import dispatch_event
    return dispatch_event(body.event, body.payload)
