"""
feature_installer.py — actually install an optional feature's dependencies.

WHY THIS EXISTS
The setup wizard rendered " · installs: faster-whisper, kokoro-onnx" next to a checkbox,
POSTed to /setup/apply — which flips config FLAGS ONLY — and then reported success. The kit
marketplace had the same shape: it computed an install plan, threw it away on the confirm
branch, and toasted "Installed". Nothing was ever installed. An operator enabled Voice, was
told it worked, and got a dead feature plus a success message they had no reason to distrust.

So this module is deliberately built to be UNABLE to overstate what happened:

  * a dep is "installed" only when pip exits 0 AND its import actually resolves in this
    interpreter — a non-zero exit or an unimportable package is a failure, never a success;
  * the real pip stderr rides along on every failure, so the UI can show WHY (no network,
    no compiler, yanked version) instead of a generic "failed";
  * feature flags are applied only when every dep of that feature is present, so we never
    switch on a capability whose engine is missing;
  * packages are checked against the pip allowlist BEFORE running, so an unknown dep is
    reported as refused rather than quietly skipped.

Installs run one package at a time so a single failure is attributed to the package that
caused it and does not mask the packages that did succeed.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
from typing import Any

logger = logging.getLogger("layla")

# pip distribution name -> module name to import when verifying the install landed.
# Only differs where the two disagree; anything unlisted verifies under its own name with
# '-' translated to '_'.
DEP_IMPORT_NAMES: dict[str, str] = {
    "faster-whisper": "faster_whisper",
    "kokoro-onnx": "kokoro_onnx",
    "discord.py": "discord",
    "sentence-transformers": "sentence_transformers",
    "pillow": "PIL",
    "python-docx": "docx",
}

# Big installs (torch, cadquery) genuinely take a while on a cold cache; a stingy timeout
# reads to the user as a failure of the product rather than of the download.
DEFAULT_TIMEOUT_SEC = 1800


def import_name_for(dep: str) -> str:
    d = str(dep or "").strip()
    return DEP_IMPORT_NAMES.get(d.lower(), d.replace("-", "_"))


def _importable(dep: str) -> bool:
    mod = import_name_for(dep)
    try:
        importlib.invalidate_caches()  # a pip install in THIS process is invisible without it
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def dep_status(deps) -> list[dict[str, Any]]:
    """Per-dep {dep, import_name, present} — lets the UI show what is already there."""
    return [
        {"dep": d, "import_name": import_name_for(d), "present": _importable(d)}
        for d in (deps or [])
    ]


def dep_present(dep: str) -> bool:
    """Is this package installed? — located WITHOUT executing it.

    `_importable` actually imports the module, which is the right check immediately after a
    pip install (it proves the thing really loads). It is the wrong check for the read paths
    that ask "is this feature real?" on every render: deriving the marketplace badge that way
    would import torch — seconds of CPU and a large RSS — just to draw a tick. find_spec
    locates the distribution without running its import side effects.
    """
    mod = import_name_for(dep)
    try:
        importlib.invalidate_caches()  # a pip install in THIS process is invisible without it
        return importlib.util.find_spec(mod) is not None
    except Exception:
        # find_spec raises (not returns None) when a PARENT package is missing.
        return False


def missing_deps(deps) -> list[str]:
    """The subset of `deps` that is not installed."""
    return [d for d in (deps or []) if not dep_present(d)]


def feature_missing_deps(feature_id: str) -> list[str]:
    """Which of a FEATURE_MANIFEST feature's packages are absent.

    This is the gate that keeps a feature flag from being switched on for an engine that is
    not there — see routers/setup_profiles.apply_setup_profiles. An unknown feature has no
    deps and therefore nothing missing.
    """
    from install.setup_profiles import feature_by_id

    feat = feature_by_id(str(feature_id or "").strip())
    return missing_deps(list(feat.get("deps") or [])) if feat else []


def feature_packages_present(feature_id: str) -> bool:
    """True when every package a feature needs is installed. A feature with no deps is
    trivially present — its capability is pure config."""
    return not feature_missing_deps(feature_id)


def install_packages(deps, *, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    """Install a list of pip packages, one at a time, and report honestly.

    Returns {ok, results:[{dep, ok, already_present, error, command, returncode}],
             installed:[dep], failed:[{dep, error}]}.
    `ok` is True only when EVERY dep ends up importable.
    """
    from services.infrastructure.dependency_recovery import (
        is_pip_allowlisted,
        pip_install_command,
        try_pip_install,
    )

    results: list[dict[str, Any]] = []
    installed: list[str] = []
    failed: list[dict[str, Any]] = []

    for dep in deps or []:
        row: dict[str, Any] = {"dep": dep, "ok": False, "already_present": False,
                               "error": "", "command": pip_install_command([dep]),
                               "returncode": None}
        if _importable(dep):
            row["ok"] = True
            row["already_present"] = True
            results.append(row)
            installed.append(dep)
            continue
        if not is_pip_allowlisted(dep):
            # Refused, not skipped — say so, or this reads as an unexplained no-op.
            row["error"] = (
                f"{dep!r} is not on the install allowlist, so it was not installed. "
                f"Install it yourself with: {row['command']}"
            )
            results.append(row)
            failed.append({"dep": dep, "error": row["error"]})
            continue

        attempt = try_pip_install([dep], timeout_sec=timeout_sec)
        row["returncode"] = attempt.get("returncode")
        if not attempt.get("ok"):
            row["error"] = str(attempt.get("error") or f"pip exited {attempt.get('returncode')}")
        elif not _importable(dep):
            # pip said 0 but the module will not import — a real, and previously invisible,
            # failure mode (wrong wheel, broken native ext, name mismatch). Not a success.
            row["error"] = (
                f"pip reported success but '{import_name_for(dep)}' still cannot be imported. "
                "The package may need a restart, or a native/system dependency it did not pull in."
            )
        else:
            row["ok"] = True

        results.append(row)
        if row["ok"]:
            installed.append(dep)
        else:
            failed.append({"dep": dep, "error": row["error"]})

    return {"ok": not failed, "results": results, "installed": installed, "failed": failed}


def install_feature_deps(feature_id: str, *, timeout_sec: int = DEFAULT_TIMEOUT_SEC,
                         apply_flags: bool = True) -> dict[str, Any]:
    """Install one FEATURE_MANIFEST feature's deps for real, then (only on full success)
    persist its config flags.

    The flags-last ordering is the point: a feature whose engine failed to install must not
    be left switched on, because every downstream surface (palette gating, capability
    manifest, the "installed" badge) reads those flags and would repeat the false claim.
    """
    from install.setup_profiles import feature_by_id

    fid = str(feature_id or "").strip()
    feat = feature_by_id(fid)
    if not feat:
        return {"ok": False, "error": f"unknown feature {fid!r}", "feature": fid}

    deps = list(feat.get("deps") or [])
    models = list(feat.get("models") or [])
    out: dict[str, Any] = {
        "ok": True,
        "feature": fid,
        "label": feat.get("label") or fid,
        "deps": deps,
        "models": models,
        "results": [],
        "installed": [],
        "failed": [],
        "flags_applied": False,
    }

    if deps:
        res = install_packages(deps, timeout_sec=timeout_sec)
        out.update({k: res[k] for k in ("ok", "results", "installed", "failed")})

    if out["ok"] and apply_flags:
        try:
            from install.setup_profiles import apply_setup

            # additive: enabling THIS feature must not wipe the operator's other choices out
            # of setup_features/setup_profiles.
            apply_setup([], [fid], save=True, additive=True)
            out["flags_applied"] = True
        except Exception as e:
            # The deps are real but the config write failed — the feature is NOT on. Say it.
            out["ok"] = False
            out["error"] = f"dependencies installed but enabling the feature failed: {e}"
            logger.warning("feature_installer: flag apply failed for %s: %s", fid, e)
    elif not out["ok"]:
        out["error"] = (
            f"{len(out['failed'])} of {len(deps)} package(s) failed to install — "
            f"'{out['label']}' was NOT enabled."
        )

    if models and out["ok"]:
        # Model weights are a separate, resumable download (/setup/download); pip installs
        # do not fetch them. Never let the caller imply the weights arrived.
        out["models_note"] = (
            "Python packages installed. Model weights (" + ", ".join(models) +
            ") download separately on first use."
        )
    return out
