"""
N1 — the setup wizard's TWO-STEP SEQUENCE must never leave a feature switched on without
its engine.

WHY THIS FILE EXISTS AT ALL
test_feature_install.py proves `install_feature_deps` does not apply flags when a dep fails.
That is true, and it was not enough: it tests the installer IN ISOLATION. The wizard drives
two calls in order — POST /setup/apply (step 1) then POST /setup/feature/install (step 2) —
and step 1 persisted the feature flags to disk before step 2 ever ran the install. So with pip
pointed at an unreachable index the screen said "The features whose packages failed were NOT
switched on" while runtime_config.json had voice_stt_prewarm_enabled: true, /setup/state
listed `voice`, the venv had neither package, and POST /voice/speak answered 503.

Nothing exercised the two calls together, which is exactly why a green 3675-test gate missed
it. These tests drive the SEQUENCE, and assert on the config ON DISK rather than on the
response body — the defect class here is "the call succeeded and the outcome is false".

No test runs a real pip install: the pip layer and the package-presence probe are stubbed.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from install import feature_installer as fi
from routers import setup_profiles as sp_router

_app = FastAPI()
_app.include_router(sp_router.router)
client = TestClient(_app)

# Every flag the `voice` feature owns — the things whose truthiness other surfaces read.
VOICE_FLAGS = ("voice_stt_prewarm_enabled", "voice_tts_prewarm_enabled")


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    """Point runtime_safety at a throwaway config so no test can touch operator state."""
    import runtime_safety as rs

    p = tmp_path / "runtime_config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", p)
    rs.invalidate_config_cache()
    yield p
    rs.invalidate_config_cache()


def _disk(cfg_file) -> dict:
    """What is persisted. NOT the same thing as what the app runs on — see `_effective`."""
    return json.loads(cfg_file.read_text(encoding="utf-8"))


def _effective() -> dict:
    """What the RUNNING APP sees: the file with auto-tune and the maturity gates overlaid.

    Asserting on `_disk` alone is what let the next defect through. `hyde_enabled: true` was
    on disk and this file called that a pass — while load_config() returned False (auto-tune
    owns the key on CPU tiers), /setup/state omitted the feature, and the palette hid it. A
    test that reads the file cannot see a value that is reverted at read time, so it passes
    PRECISELY in the scenario where the product lies. Config assertions belong here.
    """
    import runtime_safety as rs

    rs.invalidate_config_cache()
    return dict(rs.load_config())


@pytest.fixture()
def no_packages(monkeypatch):
    """Nothing is installed — the state of a fresh box ticking 'Voice'."""
    monkeypatch.setattr(fi, "dep_present", lambda dep: False)


@pytest.fixture()
def all_packages(monkeypatch):
    monkeypatch.setattr(fi, "dep_present", lambda dep: True)


@pytest.fixture()
def no_auto_tune(monkeypatch, cfg_file):
    """Take auto-tune out of the picture so a test can assert "asked == effective".

    Auto-tune is AUTHORITATIVE for hyde_enabled / multi_agent_orchestration_enabled and holds
    both off on every CPU tier, so without this a config assertion about those keys reports
    the test runner's hardware, not the code under test. Tests that want auto-tune in play
    stub the tier explicitly (see test_feature_status_readback.py).
    """
    import json as _json

    import runtime_safety as rs

    cur = _json.loads(cfg_file.read_text(encoding="utf-8"))
    cur["auto_tune_enabled"] = False
    cfg_file.write_text(_json.dumps(cur), encoding="utf-8")
    rs.invalidate_config_cache()
    yield


@pytest.fixture()
def pip_is_broken(monkeypatch):
    """pip pointed at an unreachable index — the live repro, with a trailing newline on the
    stderr exactly as pip emits it (see the _lastLine fix in the two JS callers)."""
    monkeypatch.setattr(
        "services.infrastructure.dependency_recovery.try_pip_install",
        lambda pkgs, timeout_sec=0: {
            "ok": False, "returncode": 1,
            "error": "ERROR: No matching distribution found for " + pkgs[0] + "\n",
        },
    )
    monkeypatch.setattr(fi, "_importable", lambda dep: False)


# ── step 1 alone: apply must not switch on what it cannot run ────────────────────
def test_apply_does_not_enable_a_feature_whose_packages_are_missing(cfg_file, no_packages):
    """THE regression test for N1. Step 1 in isolation: tick Voice, apply, and the flags must
    not be on disk — because step 2 has not installed anything yet and might never succeed."""
    d = client.post("/setup/apply", json={"profiles": ["minimal"], "features": ["voice"]}).json()
    assert d["ok"] is True

    cfg = _disk(cfg_file)
    for flag in VOICE_FLAGS:
        assert not cfg.get(flag), f"{flag} was persisted before its packages were installed"
    assert "voice" not in cfg.get("setup_features", [])
    # ...and the response says so, rather than counting it among the enabled.
    assert "voice" not in d["features"]
    assert "voice" in d["deferred"]
    assert any(x["id"] == "voice" for x in d["to_install"])


def test_apply_enables_a_feature_whose_packages_are_already_there(cfg_file, all_packages):
    """The other half: deferral must not become a blanket refusal. Packages present → the
    feature is genuinely usable and must be switched on immediately."""
    d = client.post("/setup/apply", json={"profiles": ["minimal"], "features": ["voice"]}).json()

    cfg = _disk(cfg_file)
    for flag in VOICE_FLAGS:
        assert cfg.get(flag) is True, f"{flag} should be on — its packages are installed"
    assert "voice" in cfg["setup_features"]
    assert d["deferred"] == []


def test_dependency_free_features_are_enabled_immediately(cfg_file, no_packages, no_auto_tune):
    """A feature with no deps is pure config; there is nothing to install and nothing to
    defer. Gating it on packages would break every flag-only feature.

    Asserted on the EFFECTIVE config, and with auto-tune off — because `hyde_enabled` is a key
    auto-tune owns, so on a CPU box the disk-only version of this assertion passed while the
    feature was off everywhere that matters. With no other owner in play, effective == asked.
    """
    d = client.post("/setup/apply", json={"profiles": ["coding"], "features": ["hyde"]}).json()
    cfg = _effective()
    assert cfg.get("hyde_enabled") is True
    assert cfg.get("mcp_client_enabled") is True  # implied by the `coding` profile
    assert "hyde" in cfg["setup_features"]
    # …and the response agrees, because it re-read the same thing rather than echoing the ask.
    assert "hyde" in d["features"] and "mcp" in d["features"]
    assert d["not_enabled"] == []


def test_a_profile_implied_feature_is_deferred_too(cfg_file, no_packages):
    """The `language` profile IMPLIES voice — the user never ticks a box. A deferral built on
    filtering the explicit `features` list would miss this entirely and re-open the defect."""
    d = client.post("/setup/apply", json={"profiles": ["language"], "features": []}).json()

    cfg = _disk(cfg_file)
    for flag in VOICE_FLAGS:
        assert not cfg.get(flag), f"{flag} on from a profile-implied feature with no packages"
    assert "voice" in d["deferred"]
    assert "language" in cfg["setup_profiles"]  # the profile itself still applies


# ── the full two-step sequence, in order ─────────────────────────────────────────
def test_failed_install_leaves_the_feature_off_end_to_end(cfg_file, no_packages, pip_is_broken):
    """THE SEQUENCE. Step 1 apply, then step 2 install with pip unreachable — precisely the
    live repro. The screen said the feature was not enabled; the disk said it was. Both must
    now say off."""
    step1 = client.post("/setup/apply", json={"profiles": ["minimal"], "features": ["voice"]}).json()
    assert "voice" in step1["deferred"]

    step2 = client.post("/setup/feature/install",
                        json={"feature_id": "voice", "confirm": True}).json()
    assert step2["ok"] is False
    assert step2["flags_applied"] is False
    assert "NOT enabled" in step2["error"]

    cfg = _disk(cfg_file)
    for flag in VOICE_FLAGS:
        assert not cfg.get(flag), f"{flag} is ON after a failed install — the N1 defect"
    assert "voice" not in cfg.get("setup_features", [])

    # And the surface the palette reads agrees.
    state = client.get("/setup/state").json()
    assert "voice" not in state["enabled_features"]


def test_successful_install_switches_the_feature_on(cfg_file, monkeypatch):
    """The success path must still work — an install that lands has to flip the flags, or the
    fix for N1 would just be a different lie."""
    present = {"v": False}  # the packages genuinely arrive between the two steps
    monkeypatch.setattr(fi, "dep_present", lambda dep: present["v"])
    step1 = client.post("/setup/apply", json={"profiles": ["minimal"], "features": ["voice"]}).json()
    assert "voice" in step1["deferred"]
    assert not _effective().get("voice_stt_prewarm_enabled")

    # Now pip works and the packages import.
    monkeypatch.setattr(
        "services.infrastructure.dependency_recovery.try_pip_install",
        lambda pkgs, timeout_sec=0: {"ok": True, "returncode": 0},
    )
    monkeypatch.setattr(fi, "_importable", lambda dep: True)
    present["v"] = True
    step2 = client.post("/setup/feature/install",
                        json={"feature_id": "voice", "confirm": True}).json()
    assert step2["ok"] is True and step2["flags_applied"] is True
    # The route re-reads the effective config before claiming success, and says so.
    assert step2["status"]["on"] is True and step2["status"]["status"] == "on"

    cfg = _effective()
    for flag in VOICE_FLAGS:
        assert cfg.get(flag) is True, f"{flag} should be on after a verified install"
    assert "voice" in cfg["setup_features"]


def test_installing_one_feature_keeps_the_others(cfg_file, monkeypatch):
    """`apply_setup([], [fid])` REPLACED setup_features, so completing a Voice install reset
    the list to ["voice"] and erased every other choice the operator had made."""
    monkeypatch.setattr(fi, "dep_present", lambda dep: True)
    client.post("/setup/apply", json={"profiles": ["coding"], "features": ["hyde", "initiative"]})
    before = set(_disk(cfg_file)["setup_features"])
    assert {"hyde", "initiative", "mcp"} <= before

    monkeypatch.setattr(
        "services.infrastructure.dependency_recovery.try_pip_install",
        lambda pkgs, timeout_sec=0: {"ok": True, "returncode": 0},
    )
    monkeypatch.setattr(fi, "_importable", lambda dep: True)
    client.post("/setup/feature/install", json={"feature_id": "voice", "confirm": True})

    after = set(_disk(cfg_file)["setup_features"])
    assert before <= after, f"installing voice erased {sorted(before - after)}"
    assert "voice" in after
    assert _disk(cfg_file)["setup_profiles"] == ["coding"]  # not clobbered either


# ── N8: a flag is not a capability ───────────────────────────────────────────────
def test_setup_state_does_not_claim_fabrication_on_a_virgin_config(cfg_file, no_packages):
    """geometry_frameworks_enabled ships as a truthy per-backend dict, so /setup/state reported
    `fabrication` as enabled on a box with no cadquery, no trimesh and no ezdxf — and it drives
    palette gating, so the CAD entries were offered and could only fail."""
    cfg_file.write_text(json.dumps({
        "geometry_frameworks_enabled": {"cadquery": True, "trimesh": True, "openscad": True, "ezdxf": True},
    }), encoding="utf-8")
    import runtime_safety as rs
    rs.invalidate_config_cache()

    state = client.get("/setup/state").json()
    assert "fabrication" not in state["enabled_features"]
    # Reported honestly rather than dropped in silence.
    assert "fabrication" in state["flagged_but_missing_packages"]


def test_setup_state_lists_a_feature_whose_packages_are_present(cfg_file, all_packages):
    cfg_file.write_text(json.dumps({
        "voice_stt_prewarm_enabled": True, "voice_tts_prewarm_enabled": True,
    }), encoding="utf-8")
    import runtime_safety as rs
    rs.invalidate_config_cache()

    assert "voice" in client.get("/setup/state").json()["enabled_features"]


# ── N5: no strong-copyleft package behind a plain checkbox ───────────────────────
def test_voice_deps_match_the_voice_extra_and_exclude_kokoro():
    """kokoro-onnx pulls phonemizer-fork (GPLv3+). pyproject keeps it out of [voice]/[all],
    README documents it as an explicit `layla[voice-kokoro]` opt-in, and check_copyleft.py
    FAILS CI on it. Wiring the installer turned this manifest string into a real
    `pip install kokoro-onnx` behind a one-click checkbox with no licence notice."""
    from install.setup_profiles import feature_by_id

    deps = feature_by_id("voice")["deps"]
    assert "kokoro-onnx" not in deps, "one-click Voice must not install a GPLv3 dependency"
    assert "faster-whisper" in deps and "pyttsx3" in deps, "must match the layla[voice] extra"


def test_no_manifest_feature_installs_a_strong_copyleft_package():
    """Generalised: whatever the manifest grows next, a checkbox must not install copyleft."""
    from install.setup_profiles import FEATURE_MANIFEST

    banned = {"kokoro-onnx", "phonemizer-fork"}
    offenders = sorted(
        f["id"] for f in FEATURE_MANIFEST if banned & {d.lower() for d in (f.get("deps") or [])}
    )
    assert offenders == [], f"features installing copyleft deps without consent: {offenders}"


def test_apply_setup_does_not_overwrite_the_operators_request_with_the_effective_config(
    cfg_file, monkeypatch
):
    """The merge base must be the REQUEST, not the answer.

    `apply_setup` read `load_config()` — the EFFECTIVE config, with auto-tune and the maturity
    gates already overlaid — used it as the merge base, and wrote the result back to disk. That
    persists every owner-imposed value as though the operator had chosen it. Driven against the
    real endpoint: a bare POST /setup/apply took the config file from 13 keys to 434, rewriting
    max_runtime_seconds 30 -> 300 and hyde_enabled True -> False, and the not-in-force report
    then read all-clear, because its entire evidence is `file != effective` and this had just
    erased the difference. Two unrelated outstanding requests were destroyed by a single feature
    install, and the wizard AUTO-OPENS on first run — so it happened before a new operator had
    knowingly chosen anything.

    This is data loss, not a reporting bug: the file is the only record of intent, and once the
    imposed value is written there, locking the key or upgrading the hardware cannot recover what
    was asked for.

    The overlay here is deliberately anonymous. WHICH owner caused effective to differ from the
    file is irrelevant — auto-tune, a maturity gate, or one nobody has written yet — so the test
    pins the invariant rather than one owner's behaviour.
    """
    import runtime_safety as rs

    from install.setup_profiles import apply_setup

    request = {
        "max_runtime_seconds": 30,
        "hyde_enabled": True,
        "inline_initiative_enabled": True,
    }
    cfg_file.write_text(json.dumps(request, indent=2), encoding="utf-8")
    rs.invalidate_config_cache()

    # An owner overlays the request: effective != file. `_owner_only` exists ONLY in the effective
    # view, so if it turns up on disk we know the whole effective config was written wholesale.
    effective = {
        **request,
        "max_runtime_seconds": 300,
        "hyde_enabled": False,
        "inline_initiative_enabled": False,
        "_owner_only": "never asked for",
    }
    monkeypatch.setattr(rs, "load_config", lambda: dict(effective))

    apply_setup([], [], save=True)

    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk.get("max_runtime_seconds") == 30, (
        "the operator asked for 30; the imposed 300 was written over it: %r" % (on_disk.get("max_runtime_seconds"),)
    )
    assert on_disk.get("hyde_enabled") is True, (
        "the operator asked for hyde_enabled=True; the imposed False was persisted"
    )
    assert on_disk.get("inline_initiative_enabled") is True, (
        "the operator asked for inline_initiative_enabled=True; the imposed False was persisted"
    )
    assert "_owner_only" not in on_disk, (
        "the effective config was written wholesale — a key that only ever existed as an owner "
        "overlay is now recorded as the operator's request"
    )
