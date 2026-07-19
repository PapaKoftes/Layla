"""
A1 — the one-click install path must actually install, and must never confirm a success
that did not happen.

Before this slice: the wizard rendered " · installs: faster-whisper, kokoro-onnx", POSTed to
/setup/apply (which flips config FLAGS ONLY), and reported "✓ configured". The only endpoint
that pip-installs anything, POST /setup/feature/install, had zero product callers. So an
operator enabled Voice, was told it worked, and got a dead feature.

These tests hold the wiring and the honesty in place. No test here runs a real pip install:
try_pip_install is always stubbed, and the "already present" fast path uses a stdlib module.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from install import feature_installer as fi
from install.setup_profiles import FEATURE_MANIFEST
from routers import setup_profiles as sp_router

_app = FastAPI()
_app.include_router(sp_router.router)
client = TestClient(_app)


# ── the allowlist must cover every dep the product offers to install ─────────────
def test_every_manifest_dep_is_pip_allowlisted():
    """try_pip_install REFUSES anything off the allowlist. A manifest dep that is not on it
    turns the wizard's "installs: X" into a silent refusal — the same lie in a new place."""
    from services.infrastructure.dependency_recovery import is_pip_allowlisted

    missing = sorted(
        {d for f in FEATURE_MANIFEST for d in (f.get("deps") or []) if not is_pip_allowlisted(d)}
    )
    assert missing == [], f"FEATURE_MANIFEST deps not on the pip allowlist: {missing}"


def test_allowlist_match_is_case_and_separator_insensitive():
    """The manifest says 'pillow'; the allowlist says 'Pillow'. An exact-string check refused
    the install over a capital letter."""
    from services.infrastructure.dependency_recovery import is_pip_allowlisted

    assert is_pip_allowlisted("pillow") and is_pip_allowlisted("Pillow")
    assert is_pip_allowlisted("faster_whisper") and is_pip_allowlisted("faster-whisper")
    assert not is_pip_allowlisted("requests-evil")


# ── install_packages: honest by construction ─────────────────────────────────────
def test_already_present_dep_is_not_reinstalled(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("pip must not run for an already-importable package")

    monkeypatch.setattr("services.infrastructure.dependency_recovery.try_pip_install", _boom)
    res = fi.install_packages(["json"])  # stdlib: always importable
    assert res["ok"] is True
    assert res["results"][0]["already_present"] is True


def test_nonzero_pip_exit_is_a_failure_not_a_success(monkeypatch):
    """`subprocess.run(..., check=True)` with the output discarded is how a failure became a
    bare exception string. A non-zero exit must fail loudly, carrying the real stderr."""
    monkeypatch.setattr(
        "services.infrastructure.dependency_recovery.try_pip_install",
        lambda pkgs, timeout_sec=0: {"ok": False, "returncode": 1,
                                     "error": "ERROR: Could not find a version that satisfies trimesh"},
    )
    # Pin the import probe: whether trimesh happens to be installed in this environment must
    # not decide whether the test exercises the failure path.
    monkeypatch.setattr(fi, "_importable", lambda dep: False)
    res = fi.install_packages(["trimesh"])
    assert res["ok"] is False
    assert res["failed"][0]["dep"] == "trimesh"
    assert "Could not find a version" in res["failed"][0]["error"]


def test_pip_says_ok_but_module_will_not_import_is_a_failure(monkeypatch):
    """The invisible failure mode: pip exits 0, the module still cannot be imported (broken
    native ext, wrong wheel). Reporting that as success is exactly the defect."""
    monkeypatch.setattr(
        "services.infrastructure.dependency_recovery.try_pip_install",
        lambda pkgs, timeout_sec=0: {"ok": True, "returncode": 0},
    )
    monkeypatch.setattr(fi, "_importable", lambda dep: False)  # pip "succeeded", import still fails
    res = fi.install_packages(["cadquery"])
    assert res["ok"] is False
    assert "cannot be imported" in res["failed"][0]["error"]


def test_no_network_surfaces_the_real_reason(monkeypatch):
    monkeypatch.setattr(
        "services.infrastructure.dependency_recovery.try_pip_install",
        lambda pkgs, timeout_sec=0: {
            "ok": False, "returncode": 1,
            "error": "WARNING: Retrying ... NewConnectionError: Failed to establish a new connection",
        },
    )
    monkeypatch.setattr(fi, "_importable", lambda dep: False)
    res = fi.install_packages(["litellm"])
    assert res["ok"] is False
    assert "connection" in res["failed"][0]["error"].lower()


def test_one_failure_does_not_mask_the_successes(monkeypatch):
    """Deps install one at a time so a failure is attributed to the package that caused it."""
    def _fake(pkgs, timeout_sec=0):
        return {"ok": pkgs[0] != "flashrank", "returncode": 0 if pkgs[0] != "flashrank" else 1,
                "error": "boom" if pkgs[0] == "flashrank" else ""}

    monkeypatch.setattr("services.infrastructure.dependency_recovery.try_pip_install", _fake)
    monkeypatch.setattr(fi, "_importable", lambda dep: dep == "torch")
    res = fi.install_packages(["torch", "flashrank"])
    assert res["installed"] == ["torch"]
    assert [f["dep"] for f in res["failed"]] == ["flashrank"]
    assert res["ok"] is False


def test_non_allowlisted_dep_is_refused_out_loud(monkeypatch):
    monkeypatch.setattr(fi, "_importable", lambda dep: False)
    res = fi.install_packages(["definitely-not-allowlisted"])
    assert res["ok"] is False
    assert "allowlist" in res["failed"][0]["error"]


# ── install_feature_deps: flags follow the packages, never lead them ─────────────
def test_flags_are_not_applied_when_a_dep_fails(monkeypatch):
    """A feature whose engine failed to install must not be left switched on — every
    downstream surface (palette gating, capability manifest, installed badge) reads those
    flags and would repeat the false claim."""
    applied = []
    monkeypatch.setattr(fi, "install_packages",
                        lambda deps, **kw: {"ok": False, "results": [], "installed": [],
                                            "failed": [{"dep": "faster-whisper", "error": "boom"}]})
    import install.setup_profiles as spm
    monkeypatch.setattr(spm, "apply_setup", lambda p, f, save=True, **kw: applied.append(f) or {})

    out = fi.install_feature_deps("voice")
    assert out["ok"] is False
    assert out["flags_applied"] is False
    assert applied == []
    assert "NOT enabled" in out["error"]


def test_flags_applied_only_after_deps_succeed(monkeypatch):
    order = []
    monkeypatch.setattr(fi, "install_packages",
                        lambda deps, **kw: (order.append("pip") or
                                            {"ok": True, "results": [], "installed": list(deps), "failed": []}))
    import install.setup_profiles as spm
    monkeypatch.setattr(spm, "apply_setup", lambda p, f, save=True, **kw: order.append("flags") or {})

    out = fi.install_feature_deps("voice")
    assert out["ok"] is True and out["flags_applied"] is True
    assert order == ["pip", "flags"], "flags must be written only after the packages land"


def test_model_weights_are_not_claimed_as_downloaded(monkeypatch):
    """Voice lists models ['whisper-base','kokoro']; pip does not fetch weights. Saying
    "installed" without qualification would overstate what happened."""
    monkeypatch.setattr(fi, "install_packages",
                        lambda deps, **kw: {"ok": True, "results": [], "installed": list(deps), "failed": []})
    import install.setup_profiles as spm
    monkeypatch.setattr(spm, "apply_setup", lambda p, f, save=True, **kw: {})
    out = fi.install_feature_deps("voice")
    assert "download separately" in out["models_note"]


def test_unknown_feature_is_rejected():
    assert fi.install_feature_deps("nope")["ok"] is False


def test_import_name_mapping():
    assert fi.import_name_for("faster-whisper") == "faster_whisper"
    assert fi.import_name_for("discord.py") == "discord"
    assert fi.import_name_for("pillow") == "PIL"
    assert fi.import_name_for("sentence-transformers") == "sentence_transformers"
    assert fi.import_name_for("litellm") == "litellm"


# ── the endpoint the wizard now calls ────────────────────────────────────────────
def test_endpoint_plan_branch_does_not_install(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("a probe must never trigger an install")

    monkeypatch.setattr(fi, "install_feature_deps", _boom)
    d = client.post("/setup/feature/install", json={"feature_id": "voice"}).json()
    assert d["ok"] is True and d["confirmed"] is False
    assert "faster-whisper" in d["plan"]["deps"]
    assert isinstance(d["dep_status"], list)


def test_endpoint_confirm_runs_the_installer(monkeypatch):
    """The confirm branch delegates to the installer — and no longer passes its `ok` through.

    The installer reporting success means "pip landed the packages and I wrote the flags". That
    is NOT the same statement as "the feature is on", because the installer cannot see the other
    owners of those keys (auto-tune, the maturity gate). So the route re-reads the effective
    config and reports THAT. Here the installer is stubbed and nothing is actually enabled, so
    the honest answer is ok=False with the reason — asserting ok=True would be asserting the
    inference this endpoint was changed to stop making.
    """
    seen = {}
    monkeypatch.setattr(fi, "install_feature_deps",
                        lambda fid, **kw: seen.setdefault("fid", fid) and None or
                        {"ok": True, "feature": fid, "installed": ["faster-whisper"], "failed": []})
    d = client.post("/setup/feature/install", json={"feature_id": "voice", "confirm": True}).json()
    assert seen["fid"] == "voice"
    assert d["confirmed"] is True
    assert d["ok"] is False, "a stubbed install enabled nothing — success must not be claimed"
    assert d["status"]["on"] is False and d["status"]["reason"]
    assert "not in force" in d["error"]


def test_endpoint_confirm_reports_success_when_the_feature_really_is_on(monkeypatch):
    """The other half: when the read-back agrees the feature is in force, `ok` stays True."""
    monkeypatch.setattr(fi, "install_feature_deps",
                        lambda fid, **kw: {"ok": True, "feature": fid, "installed": [], "failed": []})
    monkeypatch.setattr(fi, "dep_present", lambda dep: True)
    import runtime_safety
    monkeypatch.setattr(runtime_safety, "load_config",
                        lambda: {"voice_stt_prewarm_enabled": True, "voice_tts_prewarm_enabled": True})

    d = client.post("/setup/feature/install", json={"feature_id": "voice", "confirm": True}).json()
    assert d["ok"] is True and d["status"]["on"] is True


def test_endpoint_reports_failure_with_the_reason(monkeypatch):
    monkeypatch.setattr(
        fi, "install_feature_deps",
        lambda fid, **kw: {"ok": False, "feature": fid, "installed": [],
                           "failed": [{"dep": "kokoro-onnx", "error": "no matching distribution"}],
                           "error": "1 of 2 package(s) failed to install — 'Voice' was NOT enabled."},
    )
    d = client.post("/setup/feature/install", json={"feature_id": "voice", "confirm": True}).json()
    assert d["ok"] is False
    assert d["failed"][0]["dep"] == "kokoro-onnx"
    assert "NOT enabled" in d["error"]


def test_apply_returns_the_install_plan_the_wizard_must_act_on(monkeypatch):
    """/setup/apply has always returned `to_install`; the wizard discarded it. If this field
    ever disappears, the wizard silently stops offering to install anything."""
    import install.setup_profiles as spm
    monkeypatch.setattr(spm, "apply_setup",
                        lambda p, f, save=True, **kw: {"setup_profiles": list(p), "setup_features": []})
    # `to_install` is now driven by which packages are MISSING, so pin that probe — otherwise
    # this passes or fails on whether the test box happens to have faster-whisper installed.
    monkeypatch.setattr(fi, "dep_present", lambda dep: False)
    d = client.post("/setup/apply", json={"profiles": ["language"]}).json()
    assert d["ok"] is True
    assert any(x["id"] == "voice" and "faster-whisper" in x["deps"] for x in d["to_install"])


@pytest.mark.parametrize("fid", [f["id"] for f in FEATURE_MANIFEST if f.get("deps")])
def test_every_dep_bearing_feature_is_installable(fid, monkeypatch):
    """Every feature the wizard advertises deps for must reach the installer without being
    refused for an unknown package or a bad import-name guess."""
    monkeypatch.setattr(
        "services.infrastructure.dependency_recovery.try_pip_install",
        lambda pkgs, timeout_sec=0: {"ok": True, "returncode": 0},
    )
    monkeypatch.setattr(fi, "_importable", lambda dep: True)
    import install.setup_profiles as spm
    monkeypatch.setattr(spm, "apply_setup", lambda p, f, save=True, **kw: {})
    out = fi.install_feature_deps(fid)
    assert out["ok"] is True, out.get("error")
