"""Kit marketplace router (BL-156) — browse + install curated capability kits."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["kits"])


@router.get("/kits/catalog")
def kits_catalog():
    """The curated kit catalog + which are currently installed (all feature flags on)."""
    from services.skills.kit_catalog import installed_status, list_catalog

    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}
    return {"ok": True, "kits": list_catalog(), "installed": installed_status(cfg)}


@router.post("/kits/install")
def kits_install(body: dict):
    """Install a kit. Returns the plan by default; pass {"confirm": true} to apply (BL-204 pattern)."""
    from services.skills.kit_catalog import install_kit

    body = body or {}
    kit_id = str(body.get("kit_id") or body.get("id") or "").strip()
    return install_kit(kit_id, confirm=bool(body.get("confirm")))
