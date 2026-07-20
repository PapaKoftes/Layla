"""
feature_status.py — read back what is ACTUALLY in force, and say who decided it.

WHY THIS EXISTS
The setup wizard used to INFER its outcome: "what you requested, minus the packages that
failed to install". That inference has exactly one owner in it — the package installer —
and packages are only one of several reasons a feature can end up off. Driven live on a
CPU box, ticking "Power user" produced:

    wizard says enabled : [mcp, hyde, initiative, engineering, cloud_models, multi_agent, …]
    runtime_config.json : hyde_enabled true, initiative_engine_enabled true, multi_agent… true
    load_config()       : all three FALSE
    /setup/state        : all three absent — and absent from the "missing packages" list too

…because services/infrastructure/auto_tune.py owns hyde_enabled and
multi_agent_orchestration_enabled on every CPU tier, and runtime_safety's maturity gate owns
the initiative flags below rank 1. None of those three features HAS packages, so a
package-shaped gate can never see them. The user was told three features were on, the palette
hid them, and nothing explained why.

THE PRINCIPLE THIS MODULE IMPLEMENTS
    NEVER REPORT AN OUTCOME YOU INFERRED. RE-READ THE EFFECTIVE STATE AND REPORT THAT.

So: after anything writes config, ask load_config() — the same path the running app reads —
what is true now, and derive each feature's status from that. The write-then-read gap is the
whole point; a value that is reverted at read time is invisible to anything that reads the
file it was written to.

AND WHY IT IS AN OWNER REGISTRY, NOT THREE MORE SPECIAL CASES
Teaching the deferral logic about auto-tune and maturity would fix today's two owners and
leave the shape intact for the fifth owner to reintroduce (a flag gated on free disk space, a
licence check, whatever). Instead, `_OWNERS` is an ordered list of probes, and the LAST one
always matches: an owner nobody recognises still yields "on: no — reason unknown", never a
silent success. A new owner improves the message; its absence can no longer produce a lie.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("layla")

# Status values. UNKNOWN is deliberately its own outcome and not a synonym for OFF: a
# transport failure, or a cfg we could not load, means we do not KNOW — and reporting "not
# switched on" from a lost HTTP response is the same class of lie as reporting success from
# one (the server completes the write either way).
ON = "on"
OFF = "off"
UNKNOWN = "unknown"


def effective_config() -> dict:
    """The config the RUNNING APP sees — not the file.

    The distinction is the entire defect: runtime_config.json is an input to load_config(),
    which then overlays auto-tune and the maturity gates on top. Reading the file tells you
    what was requested; only this tells you what is in force.
    """
    import runtime_safety

    runtime_safety.invalidate_config_cache()  # a write we just made must not read as stale
    return dict(runtime_safety.load_config())


def _off_flags(feat: dict, cfg: dict) -> list[str]:
    """Which of the feature's flag keys do NOT hold their DECLARED value in the effective config.

    S2: this asked `not cfg.get(k)` — truthiness — so only a falsy revert was caught. See
    setup_profiles.flag_satisfied for why the declared value is the right comparison, and why
    it lives at the declaration site rather than being decided again here.
    """
    from install.setup_profiles import flag_satisfied

    return [k for k, want in (feat.get("flags") or {}).items()
            if not flag_satisfied(cfg.get(k), want)]


# ── KEY-level owner probes — THE registry ───────────────────────────────────────
# Each probe answers "is key K mine, and am I holding it away from what was written?" and, if
# so, explains it in terms the operator can act on. Returns (owner_id, reason) or None.
#
# These are keyed on the CONFIG KEY, not on a feature, because ownership is a property of the
# key: auto-tune overwrites `n_ctx` for the settings panel and `hyde_enabled` for the wizard by
# the identical mechanism. The wizard grew this registry first; POST /settings then enumerated
# ONE owner of its own (auto-tune, hardcoded) and missed the maturity gate entirely — the
# second, divergent owner list this shape exists to prevent. Both surfaces now call `key_owner`.
#
# Order matters: the most specific/actionable owner wins. There is no "unknown" probe in this
# list on purpose — `key_owner` returning None means "no probe claims it", and each CALLER
# supplies the backstop phrased for its own surface. The backstop is never optional.

def _key_owner_auto_tune(key: str, cfg: dict) -> tuple[str, str] | None:
    """auto_tune.PROFILE_KEYS are applied AUTHORITATIVELY at config load, so for a key it owns
    the file value is irrelevant — it is overwritten on every read."""
    if not cfg.get("auto_tune_enabled", True):
        return None
    try:
        from services.infrastructure.auto_tune import PROFILE_KEYS, compute_optimization_profile
    except Exception:
        return None
    if key not in PROFILE_KEYS:
        return None
    if key in set(cfg.get("auto_tune_locked_keys") or []):
        return None  # the escape hatch is engaged — the user's value wins, so this isn't us
    # The PROFILE decides: auto-tune only overwrites keys it actually emits for this tier.
    # (The old probe read `_PIPELINE[tier]`, which is HALF the profile — the pipeline-weight
    # half — so every inference key it owns, n_ctx and n_batch included, was invisible to it.)
    profile = compute_optimization_profile()
    if key not in profile:
        return None
    tier = profile.get("_opt_tier") or cfg.get("_auto_tune_tier")
    return (
        "auto_tune",
        f"auto-tune owns '{key}' on this machine's hardware tier ({tier}) and sets it to "
        f"{profile[key]!r} on every config load — your value is written to disk and then "
        f"overwritten before anything reads it. To override: add '{key}' to "
        f"auto_tune_locked_keys, or set auto_tune_enabled=false.",
    )


def _key_owner_maturity(key: str, cfg: dict) -> tuple[str, str] | None:
    """runtime_safety.MATURITY_GATED_KEYS are forced False below their rank, at config load."""
    try:
        from runtime_safety import MATURITY_GATED_KEYS, current_maturity_rank
    except Exception:
        return None
    need = MATURITY_GATED_KEYS.get(key)
    if need is None:
        return None
    rank = current_maturity_rank()
    if rank is None:
        return None  # the gate is not being applied at all — not our doing
    if rank >= need:
        return None
    return (
        "maturity",
        f"'{key}' unlocks at maturity rank {need}; Layla is at rank {rank}, so it is forced "
        "off on every config load. It switches itself on as she levels up — nothing to install.",
    )


def _key_owner_security_policy(key: str, cfg: dict) -> tuple[str, str] | None:
    """The config WRITE PATH refuses to persist remote_enabled with no credential — enabling it
    would make every request, localhost included, 403 and lock the operator out.

    This probe used to describe a refusal only `apply_setup` performed, which is why
    get_feature_themes had to document that naming it on the settings path would be "a
    confident, actionable, wrong reason": the settings surfaces wrote remote_enabled anyway.
    The refusal now lives in runtime_safety.CONFIG_INVARIANTS, so it applies to every writer
    and this probe is true on every path that can reach it.

    The credential test is `runtime_safety.remote_credential_present`, NOT a second copy of the
    comparison — it also resolves keyring-stored secrets and knows that a `remote_api_key`
    without `allow_legacy_remote_api_key` cannot authenticate anyone. The looser inline test
    that used to be here would report "you have a credential" for a config that in fact locks
    every request out.
    """
    if key != "remote_enabled":
        return None
    from runtime_safety import remote_credential_present

    if remote_credential_present(cfg):
        return None
    return (
        "security_policy",
        "remote access refuses to switch on without an auth credential (it would 403 every "
        "request, including localhost, and lock you out of this machine). Rotate a tunnel "
        "token via /remote/token/rotate — or set remote_api_key together with "
        "allow_legacy_remote_api_key — and then enable it.",
    )


_KEY_OWNERS: list[Callable[[str, dict], "tuple[str, str] | None"]] = [
    _key_owner_auto_tune,
    _key_owner_maturity,
    _key_owner_security_policy,
]


def key_owner(key: str, cfg: dict) -> tuple[str, str] | None:
    """(owner, reason) for the subsystem holding `key` away from its written value, or None.

    Call this only for a key you have ALREADY established is not in force (effective value !=
    what was written). None means "no probe claims it" — which is a gap in this registry, never
    evidence the write landed. Every caller must turn None into an honest "did not take effect,
    reason unknown"; see `explain_off` and route_helpers.sync_save_settings.
    """
    for probe in _KEY_OWNERS:
        try:
            hit = probe(key, cfg)
        except Exception as e:  # a broken probe must not silence the report
            logger.debug("feature_status: key owner probe %s failed: %s", probe.__name__, e)
            continue
        if hit:
            return hit
    return None


KNOWN_OWNERS = "packages, auto-tune, maturity, security policy"


def key_missing_packages(key: str) -> list[str]:
    """Packages that any FEATURE_MANIFEST feature declaring `key` needs and that are absent.

    Packages are declared per FEATURE, not per key, so a surface that toggles raw flags (the
    feature-theme checkboxes) had no way to ask "is this capability's engine installed?" and
    therefore never did. GET /settings/themes reported the "Advanced retrieval & search" area
    as enabled:true on a box with no elasticsearch package — advertising a capability whose
    engine is absent — because a flag being true was the whole test.

    Derived by walking the manifest rather than by a second hand-written flag->package map:
    add a dep to a feature and every flag it declares inherits the check.
    """
    from install.feature_installer import missing_deps
    from install.setup_profiles import FEATURE_MANIFEST

    deps: list[str] = []
    for feat in FEATURE_MANIFEST:
        if key in (feat.get("flags") or {}):
            for d in feat.get("deps") or []:
                if d not in deps:
                    deps.append(d)
    return missing_deps(deps)


# ── feature-level probes — a thin layer over the key registry ───────────────────

def _owner_packages(feat: dict, off_keys: list[str], cfg: dict) -> tuple[str, str] | None:
    """The one genuinely FEATURE-scoped owner: packages belong to a feature, not to a key."""
    from install.feature_installer import feature_missing_deps

    missing = feature_missing_deps(feat["id"])
    if not missing:
        return None
    return ("packages", "needs Python packages that are not installed: " + ", ".join(missing))


def _owner_by_key(feat: dict, off_keys: list[str], cfg: dict) -> tuple[str, str] | None:
    """Ask the shared key registry about each of the feature's off flags."""
    for key in off_keys:
        hit = key_owner(key, cfg)
        if hit:
            return hit
    return None


def _owner_unknown(feat: dict, off_keys: list[str], cfg: dict) -> tuple[str, str]:
    """THE BACKSTOP, and the reason this file is an honest report rather than a better guess.

    Something reverted these keys and none of the probes above claims it. That is a gap in
    THIS module, not evidence the feature is on — so it reports off with the keys named, and
    says plainly that the cause is unidentified. A future owner turns this message into a
    specific one; until then the user still gets the truth and something to grep for.
    """
    keys = ", ".join(off_keys) if off_keys else "its flags"
    return (
        "unknown",
        f"not in force — {keys} is off in the effective config and no known owner "
        f"({KNOWN_OWNERS}) accounts for it. Reason unknown; check Settings for these keys.",
    )


_OWNERS: list[Callable[..., Any]] = [
    _owner_packages,
    _owner_by_key,   # delegates to _KEY_OWNERS — the single registry
    _owner_unknown,  # must stay last — it always matches
]


def explain_off(feat: dict, cfg: dict) -> tuple[str, str]:
    """(owner, reason) for a feature that is not in force."""
    off_keys = _off_flags(feat, cfg)
    for probe in _OWNERS:
        try:
            hit = probe(feat, off_keys, cfg)
        except Exception as e:  # a broken probe must not silence the report
            logger.debug("feature_status: owner probe %s failed: %s", probe.__name__, e)
            continue
        if hit:
            return hit
    return _owner_unknown(feat, off_keys, cfg)


def feature_status(feature_ids, cfg: dict | None = None) -> list[dict]:
    """Per-feature ground truth for `feature_ids`, read back from the EFFECTIVE config.

    Returns [{id, label, status, on, owner, reason, missing_packages, off_flags}] in the
    order asked. `status` is one of ON / OFF / UNKNOWN. A feature is ON only when every flag
    it owns HOLDS THE VALUE THE MANIFEST DECLARES in the effective config AND its packages are
    present — a flag whose engine is missing is not a capability, and neither is a flag that
    was coerced to something merely truthy (S2).
    """
    from install.feature_installer import feature_missing_deps
    from install.setup_profiles import feature_by_id

    if cfg is None:
        try:
            cfg = effective_config()
        except Exception as e:
            # We could not read the truth. Say UNKNOWN — never fall back to what was asked for.
            logger.warning("feature_status: effective config unreadable: %s", e)
            return [
                {"id": fid, "label": (feature_by_id(fid) or {}).get("label") or fid,
                 "status": UNKNOWN, "on": False, "owner": "unreadable",
                 "reason": f"could not read the effective configuration ({e}) — "
                           "this feature's state could not be confirmed.",
                 "missing_packages": [], "off_flags": []}
                for fid in (feature_ids or [])
            ]

    setup_feats = set(cfg.get("setup_features") or [])
    out: list[dict] = []
    for fid in feature_ids or []:
        feat = feature_by_id(fid)
        if not feat:
            out.append({"id": fid, "label": fid, "status": UNKNOWN, "on": False,
                        "owner": "unknown", "reason": f"unknown feature {fid!r}",
                        "missing_packages": [], "off_flags": []})
            continue
        flags = feat.get("flags") or {}
        off_keys = _off_flags(feat, cfg)
        missing = feature_missing_deps(fid)
        # A flag-less feature has no flags to read back, so its persisted membership IS its
        # state (mirrors enabled_feature_ids).
        flags_on = (not off_keys) if flags else (fid in setup_feats)
        row = {
            "id": fid,
            "label": feat.get("label") or fid,
            "missing_packages": missing,
            "off_flags": off_keys,
        }
        if flags_on and not missing:
            row.update({"status": ON, "on": True, "owner": "", "reason": ""})
        else:
            owner, reason = explain_off(feat, cfg)
            row.update({"status": OFF, "on": False, "owner": owner, "reason": reason})
        out.append(row)
    return out


def intended_feature_ids(cfg: dict) -> list[str]:
    """Every feature this config ASKED for — persisted picks plus the ones its profiles
    imply. The intent is what makes an honest "you wanted X, X is off because Y" possible;
    without it an off feature is simply absent, which is how three of them disappeared with
    no explanation."""
    from install.setup_profiles import requested_feature_ids

    return requested_feature_ids(
        [p for p in (cfg.get("setup_profiles") or []) if isinstance(p, str)],
        [f for f in (cfg.get("setup_features") or []) if isinstance(f, str)],
    )
