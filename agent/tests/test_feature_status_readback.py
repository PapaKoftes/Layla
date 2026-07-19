"""
The setup wizard must REPORT WHAT IS IN FORCE, not what it asked for.

WHY THIS FILE EXISTS
test_setup_wizard_sequence.py already drives the two-call wizard sequence and asserts the
outcome — on the config FILE. That is the gap this file closes. runtime_config.json is an
INPUT to load_config(), which then overlays auto-tune and the maturity gates on top, so a
file assertion passes precisely in the scenario where the product lies:

    wizard says enabled : hyde, initiative, multi_agent
    runtime_config.json : hyde_enabled true, initiative_engine_enabled true, multi_agent… true
    load_config()       : all three FALSE
    /setup/state        : all three absent — and NOT in flagged_but_missing_packages either

None of these three features has any packages, so the package-shaped deferral gate is
structurally blind to them: the user was told three features were on, the palette hid them,
and nothing explained why. A 3703-test green gate missed it because every test in the class
read the file that was written rather than the config the app runs on.

So the tests here assert on EFFECTIVE state — load_config() and /setup/state — and cover each
owner that can veto a feature, including the one nobody has written yet: an unrecognised
owner must still produce an honest "off, reason unknown", never a silent success.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from install import feature_installer as fi
from install.feature_status import feature_status
from routers import setup_profiles as sp_router

_app = FastAPI()
_app.include_router(sp_router.router)
client = TestClient(_app)


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    """Throwaway config — no test may touch operator state."""
    import runtime_safety as rs

    p = tmp_path / "runtime_config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", p)
    rs.invalidate_config_cache()
    yield p
    rs.invalidate_config_cache()


@pytest.fixture()
def all_packages(monkeypatch):
    monkeypatch.setattr(fi, "dep_present", lambda dep: True)


@pytest.fixture()
def cpu_tier(monkeypatch):
    """Pin auto-tune to a CPU tier regardless of the machine running the suite.

    The live repro is hardware-dependent (a GPU box would enable hyde and hide the bug), and a
    test whose outcome depends on the runner's CPU count is not a regression test. Stubbing the
    profile — not the flags — keeps the REAL apply_auto_tune overlay in the path, so this
    exercises the actual ownership mechanism.
    """
    import services.infrastructure.auto_tune as at

    monkeypatch.setattr(
        at, "compute_optimization_profile",
        lambda *a, **k: {"hyde_enabled": False, "multi_agent_orchestration_enabled": False,
                         "_opt_tier": "potato"},
    )


@pytest.fixture()
def rank_zero(monkeypatch):
    """A fresh install: maturity rank 0, so the initiative flags are gated off at load."""
    import runtime_safety as rs

    monkeypatch.setattr(rs, "current_maturity_rank", lambda: 0)


def _effective() -> dict:
    import runtime_safety as rs

    rs.invalidate_config_cache()
    return dict(rs.load_config())


# ── F1: the owner that has no packages ──────────────────────────────────────────
def test_auto_tune_reverted_feature_is_reported_off_with_the_reason(cfg_file, all_packages, cpu_tier):
    """THE case the green gate missed.

    `hyde` has no deps, so it is never deferred and the file really does get hyde_enabled:true.
    Auto-tune then overwrites it to False on every read. The wizard used to count it among the
    enabled features on the strength of the write alone."""
    d = client.post("/setup/apply", json={"profiles": ["minimal"], "features": ["hyde"]}).json()
    assert d["ok"] is True

    # The write happened — this is exactly what the old file-reading test asserted and passed on.
    assert json.loads(cfg_file.read_text(encoding="utf-8")).get("hyde_enabled") is True
    # …and it is NOT in force.
    assert _effective().get("hyde_enabled") is False

    # The response must side with the effective config, not with the write.
    assert "hyde" not in d["features"], "reported as enabled while load_config() says otherwise"
    row = next(r for r in d["not_enabled"] if r["id"] == "hyde")
    assert row["on"] is False
    assert row["owner"] == "auto_tune"
    assert "auto-tune" in row["reason"] and "potato" in row["reason"]
    # The reason must be actionable, not just a label.
    assert "auto_tune_locked_keys" in row["reason"]
    # It is NOT a package problem, and must not be filed as one.
    assert "hyde" not in d["deferred"] and row["missing_packages"] == []


def test_setup_state_explains_the_auto_tune_veto(cfg_file, all_packages, cpu_tier):
    """The palette gates on /setup/state. An absent feature with no explanation is how the
    user ends up staring at a missing menu entry they were told they had enabled."""
    client.post("/setup/apply", json={"profiles": ["minimal"], "features": ["hyde"]})

    st = client.get("/setup/state").json()
    assert "hyde" not in st["enabled_features"]
    assert "hyde" not in st["flagged_but_missing_packages"]  # it has no packages to be missing
    row = next(u for u in st["unavailable_features"] if u["id"] == "hyde")
    assert row["owner"] == "auto_tune" and "auto-tune" in row["reason"]


def test_maturity_gated_feature_is_reported_off_with_the_rank(cfg_file, all_packages, rank_zero):
    """The second owner with no packages: initiative is locked below maturity rank 1."""
    d = client.post("/setup/apply", json={"profiles": ["minimal"], "features": ["initiative"]}).json()

    assert _effective().get("initiative_engine_enabled") is False
    assert "initiative" not in d["features"]
    row = next(r for r in d["not_enabled"] if r["id"] == "initiative")
    assert row["owner"] == "maturity"
    assert "rank 1" in row["reason"] and "rank 0" in row["reason"]
    # Nothing to install — the message must not send the user hunting for a package.
    assert "pip install" not in row["reason"].lower()
    assert row["missing_packages"] == []


def test_profile_implied_features_are_read_back_too(cfg_file, all_packages, cpu_tier, rank_zero):
    """The live repro: 'Power user' implies both, and the user ticked neither."""
    d = client.post("/setup/apply", json={"profiles": ["power"], "features": []}).json()

    off = {r["id"]: r for r in d["not_enabled"]}
    for fid in ("hyde", "initiative", "multi_agent"):
        assert fid not in d["features"], f"{fid} reported on while load_config() holds it off"
        assert fid in off and off[fid]["reason"], f"{fid} vanished with no explanation"
    assert off["hyde"]["owner"] == "auto_tune"
    assert off["multi_agent"]["owner"] == "auto_tune"
    assert off["initiative"]["owner"] == "maturity"


# ── the backstop: an owner nobody has taught this module about ───────────────────
def test_an_unrecognised_owner_still_reports_honestly():
    """THE POINT OF THE OWNER REGISTRY.

    A fifth owner will appear (a flag gated on free disk space, a licence check, whatever) and
    this module will not know it. The failure mode that must never return is the silent one:
    an unexplained off flag counted as enabled. Here `engineering_pipeline_enabled` is off with
    packages present, auto-tune disabled and no maturity gate on the key — no probe claims it.
    """
    cfg = {"auto_tune_enabled": False, "engineering_pipeline_enabled": False}
    row = feature_status(["engineering"], cfg=cfg)[0]

    assert row["on"] is False and row["status"] == "off"
    assert row["owner"] == "unknown"
    assert "reason unknown" in row["reason"].lower()
    # It must name the key, so the operator has something to act on.
    assert "engineering_pipeline_enabled" in row["reason"]


def test_a_feature_that_is_really_on_is_reported_on(cfg_file, all_packages):
    """The read-back must not become a blanket denial: a feature in force reports ON with no
    reason attached."""
    row = feature_status(["mcp"], cfg={"mcp_client_enabled": True})[0]
    assert row["on"] is True and row["status"] == "on" and row["reason"] == ""


def test_missing_packages_are_still_attributed_to_packages(cfg_file, monkeypatch):
    """The original owner keeps its precise message — the registry adds owners, it does not
    blur the one that already worked."""
    monkeypatch.setattr(fi, "dep_present", lambda dep: False)
    row = feature_status(["voice"], cfg={"voice_stt_prewarm_enabled": True,
                                         "voice_tts_prewarm_enabled": True})[0]
    assert row["owner"] == "packages"
    assert "faster-whisper" in row["reason"]
    assert row["missing_packages"]


# ── F2: a lost response is UNKNOWN, not a negative outcome ───────────────────────
def test_unreadable_config_reports_unknown_not_off(monkeypatch):
    """If we cannot read the truth we must say so. Falling back to "what was requested" is the
    inference this whole module exists to delete; falling back to "off" is the same error with
    the opposite sign — and it is what the UI's transport-error branch used to do."""
    import runtime_safety as rs

    def _boom():
        raise OSError("config file is gone")

    monkeypatch.setattr(rs, "load_config", _boom)
    rows = feature_status(["mcp", "hyde"])

    assert [r["status"] for r in rows] == ["unknown", "unknown"]
    for r in rows:
        assert r["on"] is False  # not a claim of enablement…
        assert "could not be confirmed" in r["reason"]  # …and not a claim of the opposite


def test_install_readback_refuses_to_claim_success_another_owner_vetoed(cfg_file, monkeypatch, cpu_tier):
    """pip exiting 0 and the flags being written is not the same statement as "the feature is
    on". The installer cannot see the other owners, so the route re-reads instead."""
    present = {"v": False}
    monkeypatch.setattr(fi, "dep_present", lambda dep: present["v"])
    monkeypatch.setattr(
        "services.infrastructure.dependency_recovery.try_pip_install",
        lambda pkgs, timeout_sec=0: {"ok": True, "returncode": 0},
    )
    monkeypatch.setattr(fi, "_importable", lambda dep: True)

    # `ml_stack` installs real packages AND we make auto-tune veto its flag, so the install
    # genuinely succeeds while the capability does not come on.
    import services.infrastructure.auto_tune as at
    monkeypatch.setattr(at, "PROFILE_KEYS", set(at.PROFILE_KEYS) | {"embedder_prefer_quality"})
    monkeypatch.setattr(
        at, "compute_optimization_profile",
        lambda *a, **k: {"embedder_prefer_quality": False, "_opt_tier": "potato"},
    )
    monkeypatch.setitem(at._PIPELINE["potato"], "embedder_prefer_quality", False)

    present["v"] = True
    r = client.post("/setup/feature/install",
                    json={"feature_id": "ml_stack", "confirm": True}).json()

    assert r["flags_applied"] is True   # the installer did its part…
    assert r["ok"] is False             # …and the route still refuses to call that success
    assert r["status"]["on"] is False
    assert "not in force" in r["error"]
    assert r["status"]["owner"] == "auto_tune"
