"""Workflow recorder & macro engine router (BL-231)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/macros", tags=["macros"])


def _require_local(request: Request) -> JSONResponse | None:
    """Defense-in-depth (security review Finding 1): replaying a macro runs real tools —
    never let a remote caller trigger it, even if the endpoint allowlist is widened."""
    try:
        from services.safety.auth import is_direct_local
        host = request.client.host if request.client else None
        if not is_direct_local(request.headers, host):
            return JSONResponse({"ok": False, "error": "local-only endpoint"}, status_code=403)
    except Exception:
        return JSONResponse({"ok": False, "error": "trust check failed"}, status_code=403)
    return None


class RecordBody(BaseModel):
    name: str
    steps: list[dict[str, Any]]
    description: str = ""


class ReplayBody(BaseModel):
    params: dict[str, str] = {}
    confirm: bool = False
    stop_on_error: bool = True


@router.get("")
def list_macros():
    from services.skills.macros import list_macros as _list
    return {"macros": _list()}


@router.post("")
def record_macro(body: RecordBody):
    from services.skills.macros import record_macro as _rec
    return _rec(body.name, body.steps, description=body.description)


@router.get("/{macro_id}")
def get_macro(macro_id: str):
    from services.skills.macros import get_macro as _get
    m = _get(macro_id)
    return m or {"ok": False, "error": "macro not found"}


@router.delete("/{macro_id}")
def delete_macro(macro_id: str):
    from services.skills.macros import delete_macro as _del
    return _del(macro_id)


@router.post("/{macro_id}/replay")
def replay_macro(macro_id: str, body: ReplayBody, request: Request):
    _blocked = _require_local(request)
    if _blocked is not None:
        return _blocked
    from services.skills.macros import replay_macro as _replay
    return _replay(
        macro_id, params=body.params, confirm=body.confirm, stop_on_error=body.stop_on_error,
    )
