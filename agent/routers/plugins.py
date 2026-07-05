"""Plugin SDK router (BL-239) — scaffold, validate, version-pin plugins."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/plugins", tags=["plugins"])


class ScaffoldBody(BaseModel):
    name: str
    dest_dir: str = "plugins"
    description: str = ""
    author: str = ""
    version: str = "0.1.0"


class ValidateBody(BaseModel):
    manifest: dict[str, Any]


@router.get("/api-version")
def api_version():
    from services.skills.plugin_sdk import LAYLA_PLUGIN_API
    return {"layla_plugin_api": LAYLA_PLUGIN_API}


@router.post("/scaffold")
def scaffold(body: ScaffoldBody):
    from services.skills.plugin_sdk import scaffold_plugin
    return scaffold_plugin(
        body.name, body.dest_dir,
        description=body.description, author=body.author, version=body.version,
    )


@router.post("/validate")
def validate(body: ValidateBody):
    from services.skills.plugin_sdk import validate_manifest
    return validate_manifest(body.manifest)
