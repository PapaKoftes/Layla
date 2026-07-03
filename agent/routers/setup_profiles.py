"""
routers/setup_profiles.py — intent-driven onboarding backend (W-S: BL-202/203/204/206/209).

Exposes the feature manifest + use-case profiles for the "what do you want to do?" and
"optional features" onboarding steps, applies a chosen setup as the startup default, and
installs a feature's deps/models on demand.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

router = APIRouter(tags=["setup"])
logger = logging.getLogger("layla")


@router.get("/setup/profiles")
def get_setup_profiles():
    """Manifest + profiles the onboarding (and Settings → reconfigure) render from."""
    from install.setup_profiles import FEATURE_MANIFEST, PROFILES

    return {"profiles": PROFILES, "features": FEATURE_MANIFEST}


@router.post("/setup/apply")
def apply_setup_profiles(body: dict):
    """Apply chosen profile(s) + feature(s) → merge onto config + persist as the startup
    default (BL-206/209). Returns the applied selection + anything that needs installing."""
    from install.setup_profiles import apply_setup, features_to_install

    body = body or {}
    profile_ids = body.get("profiles") or body.get("profile_ids") or []
    feature_ids = body.get("features") or body.get("feature_ids") or []
    if isinstance(profile_ids, str):
        profile_ids = [profile_ids]
    if isinstance(feature_ids, str):
        feature_ids = [feature_ids]
    try:
        merged = apply_setup(profile_ids, feature_ids, save=True)
    except Exception as e:
        logger.warning("setup/apply failed: %s", e)
        return {"ok": False, "error": str(e)}
    feats = merged.get("setup_features", [])
    return {
        "ok": True,
        "profiles": merged.get("setup_profiles", []),
        "features": feats,
        "to_install": features_to_install(feats),
    }


@router.post("/setup/feature/install")
def install_feature(body: dict):
    """Install a feature's deps + model(s) on demand (BL-204). Returns the install plan;
    the real pip/model install runs only when {"confirm": true} (kept explicit so a probe
    never triggers a multi-GB download)."""
    from install.setup_profiles import feature_by_id

    body = body or {}
    fid = (body.get("feature_id") or body.get("id") or "").strip()
    feat = feature_by_id(fid)
    if not feat:
        return {"ok": False, "error": f"unknown feature {fid!r}"}
    plan = {
        "id": fid,
        "label": feat["label"],
        "deps": feat.get("deps") or [],
        "models": feat.get("models") or [],
        "size_mb": feat.get("size_mb", 0),
    }
    if not body.get("confirm"):
        return {"ok": True, "plan": plan, "confirmed": False}

    # Confirmed: install pip deps (best-effort) + toggle the feature's flags on. Model
    # downloads reuse the resumable downloader via /setup/download (driven by the UI).
    installed, failed = [], []
    for dep in plan["deps"]:
        try:
            import subprocess
            import sys

            subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", dep], check=True, timeout=1800)
            installed.append(dep)
        except Exception as e:
            failed.append({"dep": dep, "error": str(e)})
    if not failed:
        from install.setup_profiles import apply_setup

        apply_setup([], [fid], save=True)  # persist the feature's flags on
    return {"ok": not failed, "installed": installed, "failed": failed, "models": plan["models"]}
