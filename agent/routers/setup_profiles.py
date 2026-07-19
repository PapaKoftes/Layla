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


@router.get("/setup/state")
def get_setup_state():
    """Which optional features are currently USABLE — drives UI gating (BL-208): the
    command palette hides feature-tagged entries whose feature is off. Fail-open by design;
    the frontend shows everything until this resolves.

    A flag alone is not a capability. `geometry_frameworks_enabled` ships as a truthy
    per-backend dict, so a virgin config reported `fabrication` as enabled on a machine with
    no cadquery, no trimesh and no ezdxf — and the palette offered CAD entries that could only
    fail. Feature flags are ANDed with the presence of the packages the feature runs on.
    """
    from install.feature_installer import feature_packages_present
    from install.setup_profiles import enabled_feature_ids

    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}
    flagged = enabled_feature_ids(cfg)
    enabled = [f for f in flagged if feature_packages_present(f)]

    # EVERY feature this config asked for that is NOT in force, each with the reason from
    # whoever actually owns it. Without this an auto-tune-reverted or maturity-locked feature
    # is simply ABSENT from the payload: the palette hides it, the wizard said it was on, and
    # nothing anywhere explains the contradiction. `flagged_but_missing_packages` could never
    # cover these — they have no packages, so a package gate cannot see them.
    unavailable: list[dict] = []
    try:
        from install.feature_status import feature_status, intended_feature_ids

        wanted = [f for f in intended_feature_ids(cfg) if f not in enabled]
        unavailable = [
            {"id": r["id"], "label": r["label"], "owner": r["owner"], "reason": r["reason"],
             "missing_packages": r["missing_packages"]}
            for r in feature_status(wanted, cfg=cfg)
        ]
    except Exception as e:
        logger.warning("setup/state: could not explain unavailable features: %s", e)

    return {
        "ok": True,
        "enabled_features": enabled,
        # Flag on, engine missing — the honest name for what used to be reported as enabled.
        "flagged_but_missing_packages": [f for f in flagged if f not in enabled],
        # Asked for, not in force — with WHO turned it off and WHY.
        "unavailable_features": unavailable,
    }


@router.post("/setup/apply")
def apply_setup_profiles(body: dict):
    """Apply chosen profile(s) + feature(s) → merge onto config + persist as the startup
    default (BL-206/209). Returns the applied selection + anything that needs installing.

    INSTALL FIRST, ENABLE SECOND. This used to persist every requested feature flag and let
    the wizard run the installs afterwards, so a failed install left the flag already ON: the
    screen said "'Voice' was NOT enabled" while runtime_config.json had voice_stt_prewarm_enabled
    true, /setup/state listed `voice`, and POST /voice/speak answered 503. The flags are the
    thing every other surface reads, so that one mis-ordering re-told the lie everywhere.

    Now a feature whose packages are missing is DEFERRED, never enabled here. It is returned in
    `to_install`/`deferred`, and the only thing that can switch it on is
    /setup/feature/install, which writes flags after the packages verifiably land.

    AND THE OUTCOME IS READ BACK, NOT INFERRED. Reporting "everything you asked for, minus the
    packages that are missing" assumes the installer is the only thing that can veto a feature.
    It is not: auto_tune owns hyde_enabled/multi_agent_orchestration_enabled on every CPU tier
    and the maturity gate owns the initiative flags below rank 1 — all three have NO packages,
    so a package-shaped gate is structurally blind to them. This route therefore re-reads
    load_config() (what the app actually runs on, not the file it just wrote) and derives
    `features`/`not_enabled` from that, with the reason attributed to whoever owns the key.
    See install/feature_status.py.
    """
    from install.feature_installer import feature_missing_deps
    from install.feature_status import feature_status
    from install.setup_profiles import (
        apply_setup,
        features_to_install,
        requested_feature_ids,
    )

    body = body or {}
    profile_ids = body.get("profiles") or body.get("profile_ids") or []
    feature_ids = body.get("features") or body.get("feature_ids") or []
    if isinstance(profile_ids, str):
        profile_ids = [profile_ids]
    if isinstance(feature_ids, str):
        feature_ids = [feature_ids]

    # Everything asked for, explicit + profile-implied — then split by what is installable now.
    requested = requested_feature_ids(profile_ids, feature_ids)
    deferred = [fid for fid in requested if feature_missing_deps(fid)]
    try:
        merged = apply_setup(profile_ids, feature_ids, save=True, exclude_features=deferred)
    except Exception as e:
        logger.warning("setup/apply failed: %s", e)
        return {"ok": False, "error": str(e)}

    # THE READ-BACK. Everything below this line describes the effective config, not the
    # selection — `merged["setup_features"]` is what we asked the file to say, which is
    # precisely the value that was reported as fact while load_config() disagreed.
    status = feature_status(requested)
    on = [r["id"] for r in status if r["on"]]
    return {
        "ok": True,
        "profiles": merged.get("setup_profiles", []),
        # Actually in force right now — verified against load_config(), not assumed.
        "features": on,
        "requested": requested,
        # Per-feature ground truth: {id,label,status,on,owner,reason,missing_packages,off_flags}.
        "status": status,
        # Asked for and NOT in force, each with the reason from whoever owns it. A superset of
        # `deferred`: missing packages are only one of the ways to end up here.
        "not_enabled": [r for r in status if not r["on"]],
        # Asked for, NOT enabled — their packages are not installed yet (drives `to_install`).
        "deferred": deferred,
        "to_install": features_to_install(deferred),
    }


@router.post("/setup/feature/install")
async def install_feature(body: dict):
    """Install a feature's deps + model(s) on demand (BL-204). Returns the install plan;
    the real pip install runs only when {"confirm": true} (kept explicit so a probe never
    triggers a multi-GB download).

    This is the endpoint the wizard's "installs: X" promise is redeemed by. It used to run
    `subprocess.run(..., check=True)` with the output thrown away, which reported a bare
    exception string on failure and could not distinguish "pip exited 0 but the module still
    will not import" from a real success. It now delegates to install.feature_installer,
    which verifies each package by importing it and returns the actual pip stderr.

    pip is blocking and slow (minutes, network-bound), so it runs off the event loop —
    otherwise a torch install freezes the whole app while the UI waits on this very request.
    """
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
        from install.feature_installer import dep_status

        return {"ok": True, "plan": plan, "confirmed": False, "dep_status": dep_status(plan["deps"])}

    import asyncio

    from install.feature_installer import install_feature_deps

    res = await asyncio.to_thread(install_feature_deps, fid)
    res["confirmed"] = True

    # Read back, same principle as /setup/apply: "pip exited 0 and we wrote the flags" is not
    # the same statement as "the feature is on". Another owner can still hold the key off, and
    # the installer has no way to know that — so ask the effective config instead of inferring.
    try:
        from install.feature_status import feature_status

        st = feature_status([fid])[0]
        res["status"] = st
        if res.get("ok") and not st["on"]:
            res["ok"] = False
            res["error"] = f"packages installed, but '{st['label']}' is still not in force: {st['reason']}"
    except Exception as e:
        logger.warning("setup/feature/install: read-back failed for %s: %s", fid, e)
        res["status"] = {"id": fid, "status": "unknown", "on": False, "owner": "unreadable",
                         "reason": f"the install finished but its result could not be confirmed ({e})."}
    return res
