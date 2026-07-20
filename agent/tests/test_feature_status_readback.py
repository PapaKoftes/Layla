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


def test_wizard_asking_for_initiative_now_actually_gets_it(cfg_file, all_packages):
    """INVERTED. This used to assert the wizard installed `initiative` and the rank gate ate it.

    The wizard LISTED initiative, wrote its flags, and reported it not-enabled with "locked below
    maturity rank 1" — on a fresh install, i.e. always. Rank no longer gates anything, so asking
    for the feature is now enough to have it, which is what the wizard always claimed.
    """
    d = client.post("/setup/apply", json={"profiles": ["minimal"], "features": ["initiative"]}).json()

    assert _effective().get("initiative_engine_enabled") is True, (
        "the wizard wrote initiative_engine_enabled and load_config() still reads False — "
        "something reverted it (the maturity gate used to)"
    )
    assert "initiative" in d["features"], f"asked for, written, still not reported on: {d['not_enabled']}"


def test_profile_implied_features_are_read_back_too(cfg_file, all_packages, cpu_tier):
    """The live repro: 'Power user' implies features the user ticked neither of.

    `initiative` was in this list, held off by the maturity gate. It is not any more — the gate
    is deleted, so a profile that implies initiative now DELIVERS it, and asserting it lands in
    `not_enabled` would be pinning the defect. It is asserted enabled below instead, so this
    test still covers the implied-feature path in both directions.
    """
    d = client.post("/setup/apply", json={"profiles": ["power"], "features": []}).json()

    off = {r["id"]: r for r in d["not_enabled"]}
    for fid in ("hyde", "multi_agent"):
        assert fid not in d["features"], f"{fid} reported on while load_config() holds it off"
        assert fid in off and off[fid]["reason"], f"{fid} vanished with no explanation"
    assert off["hyde"]["owner"] == "auto_tune"
    assert off["multi_agent"]["owner"] == "auto_tune"
    assert "initiative" in d["features"], (
        f"'power' implies initiative and nothing gates it any more, yet it is not on: {off}"
    )


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


# ── F7: `key_off_reason` — why a key is off, when nobody is overriding it ─────────
#
# WHY THIS REPLACED THE MATURITY TAIL TESTS. The old F7 pinned `_key_owner_maturity`'s choice
# between two tails ("it switches itself on as she levels up" vs "reaching rank N does NOT switch
# it on"). Both sentences are now unsayable: the rank overlay is deleted, so no rank holds any key
# away from its written value and the probe with it.
#
# What replaced it is a DIFFERENT QUESTION, and keeping the two apart is the point. `key_owner`
# answers "who is overriding the value that was written" — route_helpers asks it right after a
# save, where "you have not switched it on" would be an absurd answer to give someone who just
# did. `key_off_reason` answers the nav's broader "why is this off?", for keys nobody ever wrote.
# Feeding the second question to the first sent every plain unchecked box to the `unknown`
# backstop — "no known owner accounts for it. Reason unknown" — which reads as a defect report.


def test_a_plain_off_setting_is_explained_as_a_setting_not_a_defect():
    """autonomous_mode is the panel that drove this: off, settable, and nothing is holding it."""
    from install.feature_status import key_off_reason

    on, owner, reason, missing = key_off_reason("autonomous_mode", {"autonomous_mode": False})
    assert on is False
    assert owner == "setting", f"expected the setting owner, got {owner!r}: {reason}"
    assert missing == []
    assert "Settings" in reason, f"the reason must name where the switch is:\n  {reason}"
    # The whole defect being corrected: it must not send anyone chasing a rank.
    assert "rank" not in reason.lower().replace("no rank", ""), (
        f"the copy still points at a maturity rank:\n  {reason}"
    )
    assert "Reason unknown" not in reason, "an unchecked box reported as an unexplained defect"


def test_an_on_setting_reports_on():
    from install.feature_status import key_off_reason

    on, owner, reason, _ = key_off_reason("autonomous_mode", {"autonomous_mode": True})
    assert (on, owner, reason) == (True, "", "")


def test_a_key_with_no_writer_still_gets_the_honest_defect_report():
    """The `setting` branch must be EARNED by a writer existing, never assumed.

    Teeth: a key that no surface can set must not be told "turn it on in Settings", because that
    is the exact promise the old no-writer tail existed to avoid making. Membership is computed
    from writable_config_keys(), so this covers a key that LOSES its writer later too.
    """
    from install.feature_status import key_off_reason, writable_config_keys

    key = "definitely_not_a_real_config_key"
    assert key not in writable_config_keys()
    on, owner, reason, _ = key_off_reason(key, {})
    assert on is False
    assert owner == "unknown", f"a key with no writer was claimed by {owner!r}: {reason}"
    assert "turn it on in Settings" not in reason
    assert "defect" in reason.lower(), f"the honest report must name it a defect:\n  {reason}"


def test_a_real_owner_still_beats_the_setting_explanation(cfg_file, all_packages, cpu_tier):
    """Ordering teeth: auto-tune actively overrides the operator, and that outranks 'unchecked'.

    hyde_enabled is writable AND auto-tune reverts it on this tier. If `key_off_reason` checked
    writability first it would cheerfully tell the operator to flip a switch that auto-tune
    overwrites on the next load — advice that cannot work.
    """
    from install.feature_status import key_off_reason

    on, owner, reason, _ = key_off_reason("hyde_enabled", {"hyde_enabled": False})
    assert on is False
    assert owner == "auto_tune", f"auto-tune's override was masked by {owner!r}: {reason}"
    assert "auto_tune_locked_keys" in reason


def test_the_maturity_owner_is_gone_from_the_registry():
    """Deleted, not softened — a probe that can never fire reads like live policy."""
    import install.feature_status as fs

    assert not hasattr(fs, "_key_owner_maturity")
    assert "maturity" not in fs.KNOWN_OWNERS, (
        "KNOWN_OWNERS still advertises a maturity owner, so the backstop message names an owner "
        "no probe can return."
    )


# ── F8: /setup/gate-status — the endpoint the navigation asks ────────────────────
#
# WHY. The grouped sidebar renders its lock copy from this endpoint, so whatever it returns is what
# the operator reads and acts on. It shipped with no test of its own. That mattered: its key branch
# fell through to reason="" for any key no probe claimed, which reaches the user as "this feature is
# off, and the server gave no reason" — indistinguishable from a UI bug, and precisely the vacuum
# that a confident-but-wrong hardcoded string gets written to fill. feature_status states the rule
# as "the backstop is never optional"; these pin that this endpoint obeys it too.


def _gate(**params):
    return client.get("/setup/gate-status", params=params).json()


def _write(cfg_file, values: dict):
    """Merge `values` into the throwaway config and drop the cache, so the next read is effective."""
    import runtime_safety as rs

    cur = json.loads(cfg_file.read_text(encoding="utf-8"))
    cur.update(values)
    cfg_file.write_text(json.dumps(cur), encoding="utf-8")
    rs.invalidate_config_cache()


def test_gate_status_explains_a_missing_external_credential(cfg_file, all_packages):
    """syncthing_api_key is the navigation's live case: Sync gates on it."""
    r = _gate(keys="syncthing_api_key")
    assert r["ok"] is True
    row = r["keys"][0]
    assert row["key"] == "syncthing_api_key"
    assert row["on"] is False
    assert row["owner"] == "credential"
    assert "Syncthing" in row["reason"], (
        "the Sync gate must say which program owns the key and how to get it — a user cannot act "
        f"on anything less. Got: {row['reason']!r}"
    )


def test_gate_status_never_returns_an_empty_reason_for_an_off_key(cfg_file, all_packages):
    """THE BACKSTOP. A key no probe claims must still be explained, not left blank."""
    r = _gate(keys="some_unclaimed_flag_no_probe_owns")
    row = r["keys"][0]
    assert row["on"] is False
    assert row["reason"].strip(), (
        "an off key came back with an EMPTY reason. The nav renders that as 'off, and the server "
        "gave no reason', which reads as a broken UI and invites someone to hardcode a guess."
    )
    assert row["owner"] == "unknown", (
        "a key nobody claims must be attributed to 'unknown' — naming a specific owner we did not "
        "identify is the confident-but-wrong failure this registry exists to prevent."
    )


def test_gate_status_reports_a_satisfied_key_as_on_with_nothing_to_explain(cfg_file, all_packages):
    r = _gate(keys="syncthing_api_key")
    assert r["keys"][0]["on"] is False          # unset in the stub config…
    _write(cfg_file, {"syncthing_api_key": "abc123"})   # …now provide it
    r = _gate(keys="syncthing_api_key")
    row = r["keys"][0]
    assert row["on"] is True, "a key that is set and needs no packages must read as on"
    assert row["owner"] == "" and row["reason"] == "", (
        "a satisfied key must carry no gate copy — a stale reason on an ON feature is a lock sign "
        "on an open door, which is the whole defect class this endpoint is here to avoid."
    )


def test_gate_status_answers_for_a_feature_the_operator_never_asked_for(cfg_file, all_packages, cpu_tier):
    """The reason this endpoint exists at all: /setup/state can only explain features in
    intended_feature_ids, but the nav renders a FIXED set of entries and must explain the gated
    ones whether or not anybody ever picked them."""
    _write(cfg_file, {"setup_features": [], "setup_profiles": []})   # asked for nothing
    r = _gate(features="multi_agent")
    row = r["features"][0]
    assert row["id"] == "multi_agent"
    assert row["on"] is False
    assert row["reason"], "a feature nobody selected must still get an explanation, not silence"
