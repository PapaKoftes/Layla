"""Kit marketplace catalog (UPG-37 / BL-156).

A "kit" is a curated capability bundle you can browse and install in one click. Two kinds:
  • feature kits  — enable a set of FEATURE_MANIFEST features (installs deps/models, flips flags)
    via the existing `install.setup_profiles.apply_setup`.
  • pack kits      — a skill pack pulled from a git URL via `services.skills.skill_packs`.
The catalog itself is curated + bundled (no remote registry needed); `install_kit` dispatches
to the right installer. Installed state comes from the config flags + the skill-pack registry.
"""
from __future__ import annotations

from typing import Any

# Curated starter catalog. `features` kits reference FEATURE_MANIFEST ids; `git_url` kits are
# skill packs. Keep entries additive + honest about what they turn on.
KIT_CATALOG: list[dict[str, Any]] = [
    {"id": "coding-pro", "name": "Coding Pro", "category": "coding",
     "desc": "Repo-aware coding muscle: MCP tool servers + the structured engineering pipeline.",
     "features": ["mcp", "engineering"], "icon": "⌘"},
    {"id": "researcher", "name": "Researcher", "category": "research",
     "desc": "Deeper recall for research: Elasticsearch memory search + HyDE retrieval.",
     "features": ["search_elastic", "hyde"], "icon": "❋"},
    {"id": "voice-companion", "name": "Voice Companion", "category": "companion",
     "desc": "Speak and listen — Whisper STT + system-voice TTS. (Higher-quality Kokoro TTS is "
             "GPLv3 and stays a separate opt-in: pip install layla[voice-kokoro].)",
     "features": ["voice"], "icon": "♪"},
    {"id": "privacy", "name": "Privacy Vault", "category": "security",
     "desc": "Installs AES-at-rest crypto (OS keyring). Note: no memory is marked 'sensitive' yet, "
             "so nothing is encrypted until that policy exists (BL-326).",
     "features": ["encryption"], "icon": "⊘"},
    {"id": "quality-ml", "name": "Quality ML Stack", "category": "quality",
     "desc": "Best retrieval quality — rerankers + higher-quality embeddings (heavier).",
     "features": ["ml_stack"], "icon": "◆"},
    {"id": "council", "name": "Aspect Council", "category": "companion",
     "desc": "Multi-aspect deliberation on deep-reasoning turns.",
     "features": ["multi_agent"], "icon": "◈"},
    {"id": "connected", "name": "Connected", "category": "ecosystem",
     "desc": "Reach Layla from your phone/other devices (tunnel; audit auto-on).",
     "features": ["remote"], "icon": "⌾"},
]


def list_catalog() -> list[dict[str, Any]]:
    return list(KIT_CATALOG)


def kit_by_id(kit_id: str) -> dict[str, Any] | None:
    kid = str(kit_id or "").strip()
    return next((k for k in KIT_CATALOG if k["id"] == kid), None)


def installed_status(cfg: dict | None = None) -> dict[str, bool]:
    """Which catalog kits are genuinely installed: every feature flag on AND every package
    the features need actually present.

    This read the flags alone. Immediately after a failed Voice install the marketplace
    rendered "Voice Companion ✓ installed" while the chat toolbar on the same page said
    "Voice isn't installed" — two surfaces, one config, opposite claims. The flag says what
    was *asked for*; only the packages say what is *there*, so a badge that means "installed"
    has to consult both.
    """
    try:
        from install.setup_profiles import enabled_feature_ids
        enabled = set(enabled_feature_ids(cfg or {}))
    except Exception:
        enabled = set()
    try:
        from install.feature_installer import feature_packages_present
    except Exception:
        def feature_packages_present(_fid):  # noqa: ANN001 — fail closed, never claim installed
            return False
    out: dict[str, bool] = {}
    for k in KIT_CATALOG:
        feats = k.get("features") or []
        out[k["id"]] = bool(feats) and all(
            f in enabled and feature_packages_present(f) for f in feats
        )
    return out


def install_kit(kit_id: str, *, confirm: bool = False) -> dict[str, Any]:
    """Install a kit. Feature kits return an install plan by default and only apply flags/deps
    when confirm=True (so a probe never triggers a multi-GB download). Pack kits clone on git."""
    kit = kit_by_id(kit_id)
    if not kit:
        return {"ok": False, "error": f"unknown kit {kit_id!r}"}

    if kit.get("git_url"):
        try:
            from services.skills.skill_packs import install_from_git
            res = install_from_git(kit["git_url"], name=kit["id"])
            return {"ok": bool(res.get("ok", True)), "kit": kit["id"], "pack": res}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    feats = kit.get("features") or []
    if not feats:
        return {"ok": False, "error": "kit has no features or git_url"}
    from install.setup_profiles import features_to_install
    plan = features_to_install(feats)
    if not confirm:
        return {"ok": True, "kit": kit["id"], "features": feats, "to_install": plan, "confirmed": False}

    # The confirm branch used to DISCARD `plan` and only call apply_setup — so "Install"
    # flipped flags, installed nothing, and the UI toasted "Installed <kit>". Every
    # dep-bearing kit (Voice Companion, Quality ML, Privacy Vault, Researcher) was affected.
    # Now the plan is executed, and the kit counts as installed only if it actually is.
    from install.feature_installer import install_feature_deps

    per_feature: list[dict[str, Any]] = []
    all_ok = True
    for fid in feats:
        try:
            # apply_flags=False: flags for the whole kit are applied once, below, so a kit
            # is never left half-on with one feature enabled and another dead.
            res = install_feature_deps(fid, apply_flags=False)
        except Exception as e:
            res = {"ok": False, "feature": fid, "error": str(e)}
        per_feature.append(res)
        all_ok = all_ok and bool(res.get("ok"))

    if not all_ok:
        failed = [f for r in per_feature for f in (r.get("failed") or [])]
        return {"ok": False, "kit": kit["id"], "features": feats, "confirmed": True,
                "installed": False, "per_feature": per_feature, "failed": failed,
                "error": "some dependencies failed to install — the kit was not enabled"}
    try:
        from install.setup_profiles import apply_setup
        merged = apply_setup([], feats, save=True)
        return {"ok": True, "kit": kit["id"], "features": merged.get("setup_features", feats),
                "confirmed": True, "installed": True, "per_feature": per_feature}
    except Exception as e:
        return {"ok": False, "error": str(e), "installed": False, "per_feature": per_feature}
