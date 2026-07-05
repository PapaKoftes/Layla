"""Workflow recorder & macro engine router (BL-231)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/macros", tags=["macros"])


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
def replay_macro(macro_id: str, body: ReplayBody):
    from services.skills.macros import replay_macro as _replay
    return _replay(
        macro_id, params=body.params, confirm=body.confirm, stop_on_error=body.stop_on_error,
    )
